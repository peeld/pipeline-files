"""Phase 4 gate: injected failures at every step leave only the declared record states.

For every rule of every worked-example fixture, with rollback on and off,
this generates an entity to create (a directory, or a file with content)
and a few committed neighbours that share parts of its path. It runs the
write once cleanly to learn its steps, then again with a failure injected at
each step, with a crash at each step, and with a second failure or crash at
each step the first failure leads to. After every run, and again after
recovery, it checks the record is in a declared state and that the disk
agrees with that state:

| State | Seen by queries | On disk |
| --- | --- | --- |
| No record | No | Exactly what was there before |
| Pending | No | Anything; recovery must settle it |
| Committed | Yes, nothing lagging | The entity, its sidecar and its content |
| Out of sync | Yes, with its lagging links | Anything |
| Failed | No | Exactly what was there before |

Neighbours stay committed and on disk throughout. A single failure must
also end in the exact state the write lifecycle gives for that step.
"""

from __future__ import annotations

import tempfile
from functools import cache
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from entitylayout import (
    Engine,
    FilesystemBackend,
    OutOfSyncError,
    SQLiteBackend,
    WriteError,
    WriteIncompleteError,
    WriteRolledBackError,
    load_config_data,
    read_config,
    read_sidecar,
)
from entitylayout.keys import nfc

from conftest import FIXTURE_NAMES, FIXTURES
from strategies import rule_fields

RULES = [(name, rule) for name in FIXTURE_NAMES for rule in read_config(FIXTURES / name)["rules"]]


class Crash(BaseException):
    """Stands for the process dying: the engine has no chance to clean up."""


class Injected(RuntimeError):
    pass


@cache
def fixture_layout(name, rollback):
    data = read_config(FIXTURES / name)
    for links in data["links"].values():
        for settings_ in links.values():
            if settings_["role"] == "active":
                settings_["rollback"] = rollback
    return load_config_data(data)


class Run:
    """One write in a fresh directory and database, with faults injected by checkpoint call number."""

    def __init__(self, layout, rule, neighbours, fields, content, faults):
        self.rule, self.fields, self.content = rule, fields, content
        self.faults = dict(faults)
        self.steps = []
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.layout = layout.with_roots({layout.rule(rule).root: self.root})
        self.db = SQLiteBackend(self.layout, ":memory:")
        self.stores = {}
        links = self.layout.rule(rule).links
        self.stores[links.authority.name] = self.db
        for link in links.active:
            self.stores[link.name] = FilesystemBackend(self.layout)
        self.links = links
        clean = Engine(self.layout, self.stores)
        self.neighbours = [clean.create(rule, n) for n in neighbours]
        self.before = snapshot(self.root)
        self.error = None
        try:
            Engine(self.layout, self.stores, checkpoint=self._checkpoint).create(rule, fields, content=content)
        except (WriteError, Injected, Crash) as exc:
            self.error = exc

    def _checkpoint(self, step):
        self.steps.append(step)
        fault = self.faults.get(len(self.steps) - 1)
        if fault is not None:
            raise fault(f"injected at {step}")

    def record(self):
        """The target's record, or None if it was never reserved."""
        location = self.layout.locate(self.rule, self.fields).path
        ids = [i for (i,) in self.db._conn.execute("SELECT id FROM entities WHERE location = ?", (location,))]
        assert len(ids) <= 1
        return self.db.record(ids[0]) if ids else None

    def recover(self):
        Engine(self.layout, self.stores).recover()
        assert self.db.unsettled() == [] or all(r.state == "out_of_sync" for r in self.db.unsettled())

    def close(self):
        self.db.close()
        self._tmp.cleanup()


def snapshot(root):
    """Every path under root with what it holds, so any change shows."""
    return {str(p.relative_to(root)): None if p.is_dir() else p.read_bytes() for p in sorted(root.rglob("*"))}


def check_declared(run):
    """The record is in a declared state, and queries and the disk agree with it."""
    record = run.record()
    visible = {e.id: e for e in Engine(run.layout, run.stores).query(run.rule)}
    for neighbour in run.neighbours:
        assert neighbour.id in visible and visible[neighbour.id].lagging == ()
        assert_on_disk(run, run.db.record(neighbour.id), None)
    if record is None or record.state == "failed":
        assert snapshot(run.root) == run.before
        assert record is None or record.id not in visible
        return "none" if record is None else "failed"
    if record.state == "pending":
        assert record.id not in visible
    elif record.state == "committed":
        assert visible[record.id].lagging == ()
        assert_on_disk(run, record, run.content)
    elif record.state == "out_of_sync":
        assert record.lagging and visible[record.id].lagging == record.lagging
    else:
        raise AssertionError(f"undeclared state {record.state}")
    return record.state


def assert_on_disk(run, record, content):
    path = run.layout.real_path(run.layout.locate(run.rule, record.fields))
    if record.content_hash is None:
        assert path.is_dir()
        sidecar = path / ".entitylayout.json"
    else:
        assert path.read_bytes() == content
        sidecar = path.parent / f".{path.name}.entitylayout.json"
    stamp = read_sidecar(sidecar.read_text(encoding="utf-8"), str(sidecar))
    assert (stamp.id, stamp.revision, stamp.body["content_hash"]) == (record.id, 1, record.content_hash)
    assert not stamp.edited


def content_lost(steps, index, content):
    """Whether a fault at step index came before the file was written, so recovery has no content to write."""
    file_steps = [i for i, s in enumerate(steps) if s.endswith(":file")]
    return content is not None and file_steps[0] >= index


def expected_after_failure(steps, index, rollback, content):
    """The state the write lifecycle gives for one failure at a step, and after recovery."""
    step = steps[index]
    if step == "reserve":
        return "none", "none"
    if step == "settle:committed":
        return ("failed", "failed") if rollback else ("pending", "committed")
    if rollback:
        return "failed", "failed"
    return "out_of_sync", "out_of_sync" if content_lost(steps, index, content) else "committed"


def expected_after_crash(steps, index, rollback, content):
    """After a crash, recovery realizes the write again, or undoes it if it cannot finish."""
    if steps[index] == "reserve":
        return "none"
    if content_lost(steps, index, content):
        return "failed" if rollback else "out_of_sync"
    return "committed"


@st.composite
def scenario(draw, layout, rule):
    fields = draw(rule_fields(layout, rule, int64=True))
    content = draw(st.one_of(st.none(), st.binary(max_size=16)))
    neighbours = []
    for _ in range(draw(st.integers(0, 2))):
        other = draw(rule_fields(layout, rule, int64=True))
        # Share a prefix with the target, so a rollback has parent directories it must keep.
        shared = draw(st.integers(0, len(layout.rule(rule).keys)))
        keys = layout.rule(rule).keys
        mixed = {k: fields[k] for k in keys[:shared] if k in fields}
        mixed.update({k: other[k] for k in keys[shared:] if k in other})
        neighbours.append(mixed)
    return fields, content, neighbours


def usable(layout, rule, fields, neighbours):
    """Every location is distinct, and no two differ only by case, which Windows and macOS would merge."""
    paths = [layout.locate(rule, f).path for f in (fields, *neighbours)]
    if len(set(paths)) != len(paths):
        return False
    spelled = {}
    for path in paths:
        parts = path.split("/")
        for i in range(len(parts)):
            prefix = "/".join(parts[: i + 1])
            if spelled.setdefault(nfc(prefix).casefold(), prefix) != prefix:
                return False
    return True


@pytest.mark.parametrize("rollback", [True, False], ids=["rollback", "no-rollback"])
@pytest.mark.parametrize(("fixture", "rule"), RULES)
@settings(max_examples=6)
@given(data=st.data())
def test_injected_failures_leave_only_declared_states(fixture, rule, rollback, data):
    layout = fixture_layout(fixture, rollback)
    fields, content, neighbours = data.draw(scenario(layout, rule))
    assume(usable(layout, rule, fields, neighbours))

    def run(faults):
        return Run(layout, rule, neighbours, fields, content, faults)

    clean = run({})
    assert clean.error is None
    assert check_declared(clean) == "committed"
    steps = clean.steps
    clean.close()

    for index, step in enumerate(steps):
        # One failure: the exact state the lifecycle declares, then recovery.
        failed = run({index: Injected})
        state, recovered = expected_after_failure(steps, index, rollback, content)
        assert check_declared(failed) == state, (step, failed.error)
        if state == "failed":
            assert isinstance(failed.error, WriteRolledBackError)
        elif state == "out_of_sync":
            assert isinstance(failed.error, OutOfSyncError)
        elif state == "pending":
            assert isinstance(failed.error, WriteIncompleteError)
        failed.recover()
        assert check_declared(failed) == recovered, step
        if recovered == "out_of_sync":
            # The tool that still has the content can catch the link up.
            Engine(failed.layout, failed.stores).retry(rule, failed.record().id, content=content)
            assert check_declared(failed) == "committed"
        later = failed.steps[index + 1 :]
        failed.close()

        # A crash: the record stays as the crash left it until recovery settles it.
        crashed = run({index: Crash})
        assert isinstance(crashed.error, Crash)
        assert check_declared(crashed) in ("none", "pending")
        crashed.recover()
        assert check_declared(crashed) == expected_after_crash(steps, index, rollback, content), step
        crashed.close()

        # A second fault at each step the first failure leads to, such as an undo.
        for offset in range(len(later)):
            for second in (Injected, Crash):
                double = run({index: Injected, index + 1 + offset: second})
                assert check_declared(double) in ("none", "pending", "out_of_sync", "failed", "committed")
                double.recover()
                assert check_declared(double) in ("none", "out_of_sync", "failed", "committed")
                if double.record() is not None and double.record().state == "out_of_sync":
                    # A retry with nothing failing catches the lagging links up, unless the content is gone.
                    double.recover()
                    assert check_declared(double) in ("committed", "out_of_sync")
                double.close()
