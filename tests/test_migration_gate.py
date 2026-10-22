"""Phase 6 gate: a migrated entity type keeps identity, history and every link intact.

For every worked-example fixture, the rules that share the fixture's links
move from one SQLite authority to another with the reference script in
`tests/reference_migration.py`. First a random history is played against the
old authority: directories and files created across the rules, some failed
at a step, some crashed part way, and some realized in the passive link by
its event, a few of those failed or crashed part way too.

The migration is run cleanly, then crashed at each of its steps and run
again. Each time:

- **Identity.** Every record is in the new authority with its internal ID,
  state, revision, fields, requested key, lagging links, attributes, content
  hash and config version.
- **History.** Every record's log is the same, in order, and the two
  authorities' queries agree.
- **Links.** Nothing on disk changed. Recovery and the passive link, run on
  the new authority, end exactly where they end on the old one with no
  migration: the same records, logs and disk.
- **The old authority** is unchanged. A tool still pointed at it holds new
  work instead, which merges into the new authority under its uuid.

Running the finished migration again changes nothing.
"""

from __future__ import annotations

import shutil
import tempfile
from functools import cache
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from entitylayout import Engine, FilesystemBackend, Holding, LayoutError, SQLiteBackend, load_config_data, read_config
from entitylayout.keys import nfc
from entitylayout.records import canonical_json, content_hash
from reference_migration import family, migrate
from test_write_gate import snapshot

from conftest import FIXTURE_NAMES, FIXTURES
from strategies import rule_fields


class Crash(BaseException):
    """Stands for the process dying: nothing has a chance to clean up."""


class Injected(RuntimeError):
    pass


@cache
def gate_layout(fixture):
    """The fixture with its authority holding new work while it is unreachable."""
    data = read_config(FIXTURES / fixture)
    for links in data["links"].values():
        for settings_ in links.values():
            if settings_["role"] == "authority":
                settings_["offline"] = "hold"
    return load_config_data(data)


def moving(layout):
    """The rules that move: the family that shares the fixture's links."""
    return family(layout, next(r.name for r in layout.rules.values() if r.links is not None))


class World:
    """One copy of a session under base: both authorities, the active and passive link trees and the holding area."""

    def __init__(self, layout, base):
        self.base = base
        rules = moving(layout)
        self.links = layout.rule(rules[0]).links
        root = layout.rule(rules[0]).root
        for name in ("root", "passive", "holding"):
            (base / name).mkdir(parents=True, exist_ok=True)
        self.layout = layout.with_roots({root: base / "root"})
        self.old = SQLiteBackend(self.layout, base / "old.db")
        self.new = SQLiteBackend(self.layout, base / "new.db")
        passive = FilesystemBackend(layout.with_roots({root: base / "passive"}))
        self.stores = {
            **{link.name: FilesystemBackend(self.layout) for link in self.links.active},
            **{link.name: passive for link in self.links.passive},
        }
        self.holding = Holding(self.layout, base / "holding", "laptop")

    def engine(self, authority, checkpoint=None):
        stores = {self.links.authority.name: authority, **self.stores}
        return Engine(self.layout, stores, holding=self.holding, checkpoint=checkpoint, claimant="laptop")

    def copy(self, base):
        self.close()
        shutil.copytree(self.base, base)
        return World(self.layout, base)

    def close(self):
        self.old.close()
        self.new.close()

    def records(self, authority):
        """Every moving record with its log, in order.

        Each authority numbers its log its own way, and a passive run started
        after the copies split has a new operation ID in each, so operations
        are named by the order they first appear in.
        """
        operations = {}
        return [
            (
                record,
                [
                    (operations.setdefault(s.operation, len(operations)), s.step, s.link, self._clean(s.detail))
                    for s in authority.history(record.id)
                ],
            )
            for record in authority.records(*moving(self.layout))
        ]

    def disk(self):
        return snapshot(self.base / "root"), snapshot(self.base / "passive")

    def _clean(self, detail):
        # An error message kept in the log could name a real path, which differs between copies.
        text = canonical_json(detail)
        return text.replace(canonical_json(str(self.base))[1:-1], "<base>").replace(str(self.base), "<base>")


def fault(kind, step):
    """A checkpoint that fails or crashes at step the first time it is reached."""
    pending = [step]

    def checkpoint(name):
        if name in pending:
            pending.remove(name)
            raise (Crash if kind == "crash" else Injected)(f"injected at {name}")

    return checkpoint


def no_fault(name):
    pass


def crash_at(index):
    """A checkpoint that crashes at the index-th step it is called with."""
    calls = []

    def checkpoint(name):
        calls.append(name)
        if len(calls) - 1 == index:
            raise Crash(f"injected at {name}")

    return checkpoint


@st.composite
def histories(draw, fixture):
    """Writes across the moving rules, each with an optional fault and passive run, and one entity to hold later."""
    layout = gate_layout(fixture)
    rules = moving(layout)
    links = layout.rule(rules[0]).links
    active, passive = links.active[0].name, links.passive[0].name
    write_faults = [
        None,
        ("fail", f"realize:{active}"),
        ("fail", "settle:committed"),
        ("crash", f"realized:{active}"),
        ("crash", "settle:committed"),
    ]
    passive_faults = [None, "skip", ("fail", f"realize:{passive}"), ("crash", f"{passive}:sidecar")]
    writes = []
    for _ in range(draw(st.integers(min_value=1, max_value=4))):
        rule = draw(st.sampled_from(rules))
        writes.append(
            {
                "rule": rule,
                "fields": draw(rule_fields(layout, rule, int64=True)),
                "content": draw(st.one_of(st.none(), st.binary(max_size=8))),
                "fault": draw(st.sampled_from(write_faults)),
                "passive": draw(st.sampled_from(passive_faults)),
            }
        )
    rule = draw(st.sampled_from(rules))
    held = (rule, draw(rule_fields(layout, rule, int64=True)), draw(st.one_of(st.none(), st.binary(max_size=8))))
    return {"writes": writes, "held": held}


def usable(layout, plan):
    """Paths that work the same on every platform, with the held entity apart from everything else."""
    spelled = {}
    paths = []
    for rule, fields in [*((w["rule"], w["fields"]) for w in plan["writes"]), plan["held"][:2]]:
        parts = layout.locate(rule, fields).path.split("/")
        paths.append(nfc("/".join(parts)).casefold())
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            # Two spellings that differ only by case would share a directory on Windows and macOS.
            if spelled.setdefault(nfc(prefix).casefold(), prefix) != prefix:
                return False
    held = paths[-1]
    return all(p != held and not p.startswith(held + "/") and not held.startswith(p + "/") for p in paths[:-1])


def play(world, plan):
    """Run the history against the old authority."""
    trigger = world.links.passive[0].triggers[0]
    for write in plan["writes"]:
        checkpoint = fault(*write["fault"]) if write["fault"] else no_fault
        try:
            engine = world.engine(world.old, checkpoint)
            entity = engine.create(write["rule"], write["fields"], content=write["content"])
        except (LayoutError, Crash):
            continue
        if write["passive"] == "skip":
            continue
        checkpoint = fault(*write["passive"]) if write["passive"] else no_fault
        try:
            world.engine(world.old, checkpoint).realize_passive(
                write["rule"], entity.id, event=trigger, content=write["content"]
            )
        except Crash:
            pass


def settle(world, authority, plan):
    """Recover, then run the passive link for every committed record, and say what each run did."""
    engine = world.engine(authority)
    engine.recover()
    contents = {content_hash(w["content"]): w["content"] for w in plan["writes"] if w["content"] is not None}
    trigger = world.links.passive[0].triggers[0]
    runs = []
    for record in authority.records(*moving(world.layout)):
        if record.state == "committed":
            results = engine.realize_passive(
                record.rule, record.id, event=trigger, content=contents.get(record.content_hash)
            )
            runs.append((record.id, [(r.link, r.realized) for r in results]))
    return runs


def check_moved(world, start):
    """Identity, history and links all came across, and the old authority is as it was."""
    records, disk = start
    assert world.records(world.new) == records
    assert world.records(world.old) == records
    assert world.disk() == disk
    for rule in moving(world.layout):
        assert world.new.query(rule) == world.old.query(rule)


@pytest.mark.parametrize("fixture", FIXTURE_NAMES)
@settings(max_examples=10)
@given(data=st.data())
def test_a_migrated_entity_type_keeps_identity_history_and_every_link(fixture, data):
    layout = gate_layout(fixture)
    plan = data.draw(histories(fixture))
    assume(usable(layout, plan))
    rules = moving(layout)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        world = World(layout, tmp / "start")
        play(world, plan)
        start = (world.records(world.old), world.disk())

        # Where the history ends with no migration.
        stay = world.copy(tmp / "stay")
        runs = settle(stay, stay.old, plan)
        settled = (stay.records(stay.old), stay.disk())
        stay.close()

        # The clean move. Part way through, a tool still on the old authority holds new work.
        clean = world.copy(tmp / "clean")
        steps, held = [], []

        def during(step):
            steps.append(step)
            if step.startswith("restore:") and not held:
                held.append(clean.engine(clean.old).create(*plan["held"][:2], content=plan["held"][2]))

        migrate(clean.old, clean.new, rules, checkpoint=during)
        assert held and held[0].provisional
        check_moved(clean, start)
        migrate(clean.old, clean.new, rules)
        check_moved(clean, start)
        assert settle(clean, clean.new, plan) == runs
        assert (clean.records(clean.new), clean.disk()) == settled
        # The held work merges into the new authority under its uuid, and never reached the old one.
        merged = clean.engine(clean.new).merge()
        outcomes = [(r.outcome, r.record and r.record.id) for r in merged]
        assert outcomes == [("merged", held[0].id)], [r.reason for r in merged]
        assert held[0].id not in {r.id for r in clean.old.records(*rules)}
        clean.close()

        # Crashed at each step and run again, the move ends in the same place.
        for index, step in enumerate(steps):
            crashed = world.copy(tmp / f"crashed-{index}")
            try:
                migrate(crashed.old, crashed.new, rules, checkpoint=crash_at(index))
            except Crash:
                pass
            migrate(crashed.old, crashed.new, rules)
            check_moved(crashed, start)
            assert settle(crashed, crashed.new, plan) == runs, step
            assert (crashed.records(crashed.new), crashed.disk()) == settled, step
            crashed.close()
        world.close()
