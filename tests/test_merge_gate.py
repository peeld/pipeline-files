"""Phase 5 gate: replayed offline sessions with injected clashes resolve exactly as configured.

For every rule of every worked-example fixture, this plays an offline
session. The authority goes down, and the owner creates an entity of the
rule, a directory or a file with content, sometimes after creating its parent
while still offline. The authority comes back. Before the merge, a clash is
injected on one held entity, or on none: another machine commits the same key
in the authority, or someone else's work sits at the location on disk. The
link that finds the clash has a clash rule drawn from those the rule can
carry: fail always, version_up with a version key, suffix with a suffix key.

| Clash rule | The clashing element | A held child of it |
| --- | --- | --- |
| No clash | Merged under the key asked for | Merged |
| fail | Needs a decision and stays held. No record, or a failed one, or out of sync with rollback off | Blocked |
| version_up | Rekeyed to one past the highest version, with the requested key kept | Rekeyed to follow |
| suffix | Rekeyed to the next suffix, from 2, with the requested key kept | Rekeyed to follow |

The other side of the clash is never touched. The merge is then replayed:
crashed at each of its steps and merged again by the same claimant, it must
end exactly where the uninterrupted merge ended. Merging copies of merged
elements again, and merging a settled session again, changes nothing.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from functools import cache
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from entitylayout import (
    Engine,
    FilesystemBackend,
    Holding,
    SQLiteBackend,
    UnreachableError,
    load_config_data,
    read_config,
    read_sidecar,
)
from entitylayout.holding import full_fields
from entitylayout.records import canonical_json
from test_write_gate import snapshot

from conftest import FIXTURE_NAMES, FIXTURES
from strategies import rule_fields

FOREIGN = b"someone else's work"


def _cases():
    """Every configuration a session can meet, per rule: with or without a held parent, and each clash it can take."""
    for fixture in FIXTURE_NAMES:
        layout = load_config_data(read_config(FIXTURES / fixture))
        for rule in layout.rules.values():
            for parent in (False, True) if rule.parent else (False,):
                chain = [layout.rule(rule.parent), rule] if parent else [rule]
                yield fixture, rule.name, parent, None, "authority", "fail"
                for victim, clashing in enumerate(chain):
                    hows = ["fail", *(["version_up"] if clashing.version_key else [])]
                    hows += ["suffix"] if clashing.suffix_key else []
                    for where in ("authority", "link"):
                        for how in hows:
                            yield fixture, rule.name, parent, victim, where, how


CASES = list(_cases())


def _case_id(case):
    fixture, rule, parent, victim, where, how = case
    clash = "no-clash" if victim is None else f"clash-{victim}-{where}-{how}"
    return f"{fixture}-{rule}{'-under-held-parent' if parent else ''}-{clash}"


class Crash(BaseException):
    """Stands for the process dying: the engine has no chance to clean up."""


class Switchable(SQLiteBackend):
    """An authority that can be taken offline."""

    down = False

    def reserve(self, *args, **kwargs):
        if self.down:
            raise UnreachableError("the authority is down")
        return super().reserve(*args, **kwargs)

    def query(self, *args, **kwargs):
        if self.down:
            raise UnreachableError("the authority is down")
        return super().query(*args, **kwargs)


@cache
def session_layout(fixture, victim, where, how):
    """The fixture with every rule holding offline work, and the victim rule's clash rule set at one link."""
    data = read_config(FIXTURES / fixture)
    base = load_config_data(data)
    links = {}
    for rule in base.rules.values():
        declared = data["links"][rule.links.declared_by]
        links[rule.name] = {name: dict(settings_) for name, settings_ in declared.items()}
        for settings_ in links[rule.name].values():
            if settings_["role"] == "authority":
                settings_["offline"] = "hold"
        if rule.name == victim:
            role = "authority" if where == "authority" else "active"
            for settings_ in links[rule.name].values():
                if settings_["role"] == role:
                    settings_["clash"] = how
    data["links"] = links
    return load_config_data(data)


class Session:
    """One offline session and its merge, in a fresh directory, database and holding area."""

    def __init__(self, layout, plan, faults=None):
        self.plan = plan
        self.faults = dict(faults or {})
        self.steps = []
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        (tmp / "root").mkdir()
        (tmp / "holding").mkdir()
        (tmp / "elsewhere").mkdir()
        self.root = tmp / "root"
        rule = layout.rule(plan["entities"][-1][0])
        self.layout = layout.with_roots({rule.root: self.root})
        self.db = Switchable(self.layout, ":memory:")
        links = rule.links
        self.stores = {links.authority.name: self.db, **{a.name: FilesystemBackend(self.layout) for a in links.active}}
        self.holding = Holding(self.layout, tmp / "holding", "laptop")

        # The session: the authority is down while the owner works.
        self.db.down = True
        self.held = [self.engine().create(r, f, content=c) for r, f, c in plan["entities"]]
        self.db.down = False
        self.copies = tmp / "copies"
        shutil.copytree(self.holding.path, self.copies)

        # Someone else's work at the victim's key.
        self.competitor = None
        if plan["victim"] is not None:
            r, fields, content = plan["entities"][plan["victim"]]
            other = competing(content)
            if plan["where"] == "authority":
                desk = Engine(self.layout, self.stores, holding=Holding(self.layout, tmp / "elsewhere", "desktop"))
                self.competitor = desk.create(r, fields, content=other)
            else:
                path = self.layout.real_path(self.layout.locate(r, fields))
                if content is None:
                    path.mkdir(parents=True, exist_ok=True)
                    (path / ".entitylayout.json").write_bytes(FOREIGN)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(FOREIGN)
        self.before = snapshot(self.root)
        self.ids = [h.id for h in self.held] + ([self.competitor.id] if self.competitor else [])

    def engine(self, checkpoint=None):
        return Engine(self.layout, self.stores, holding=self.holding, checkpoint=checkpoint, claimant="laptop")

    def _checkpoint(self, step):
        self.steps.append(step)
        fault = self.faults.get(len(self.steps) - 1)
        if fault is not None:
            raise fault(f"injected at {step}")

    def merge(self):
        """Merge with the faults given, then without, until no element is left part way."""
        try:
            results = self.engine(self._checkpoint).merge()
        except Crash:
            results = None
        for _ in range(4):
            if results is not None and not any(r.outcome in ("incomplete", "claimed") for r in results):
                return results
            results = self.engine().merge()
        raise AssertionError(f"the merge did not settle: {[(r.outcome, r.reason) for r in results]}")

    def state(self):
        """Where the session ended: each element's record and whether it is held, and the disk, with IDs named."""
        records = []
        for index, element in enumerate(self.held):
            record = _find(self.db, element.id)
            summary = None if record is None else (record.state, record.fields, record.requested, record.lagging)
            records.append((index, summary, self.holding.has(element.id)))
        disk = {path: _named(path, data, self.ids) for path, data in snapshot(self.root).items()}
        return records, disk

    def close(self):
        self.db.close()
        self._tmp.cleanup()


def competing(content):
    """Different content for the competing file, or None for a directory."""
    return None if content is None else FOREIGN


def _find(db, record_id):
    rows = db._conn.execute("SELECT 1 FROM entities WHERE id = ?", (record_id,)).fetchall()
    return db.record(record_id) if rows else None


def _named(path, data, ids):
    """What a file holds, with each internal ID replaced by its place in the session.

    A sidecar's stamp hashes the ID too, so a sidecar is checked and compared without its stamp.
    """
    if data is None:
        return None
    if path.endswith(".entitylayout.json") and data != FOREIGN:
        stamp = read_sidecar(data.decode("utf-8"), path)
        assert not stamp.edited
        data = json.dumps(stamp.body, sort_keys=True).encode("utf-8")
    for index, record_id in enumerate(ids):
        data = data.replace(record_id.encode(), f"<id {index}>".encode())
    return data


def expected(layout, plan):
    """The outcome and final fields the configuration gives each held entity."""
    found = []
    for index, (rule, fields, _) in enumerate(plan["entities"]):
        r = layout.rule(rule)
        requested = full_fields(layout, r, fields)
        if index > 0:
            parent_outcome, parent_final = found[0]
            if parent_outcome == "needs_decision":
                found.append(("blocked", None))
                continue
            requested_final = {**requested, **parent_final}
        else:
            requested_final = requested
        if plan["victim"] == index and plan["how"] == "fail":
            found.append(("needs_decision", None))
            continue
        final = dict(requested_final)
        if plan["victim"] == index and plan["how"] == "version_up":
            final[r.version_key] += 1
        elif plan["victim"] == index and plan["how"] == "suffix":
            final[r.suffix_key] = final.get(r.suffix_key, 1) + 1
        found.append(("rekeyed" if final != requested else "merged", final))
    return found


@st.composite
def offline_session(draw, fixture, rule, parent, victim, where, how):
    """The entities held in one session: a directory or a file of rule, after its parent if that is held too."""
    layout = load_config_data(read_config(FIXTURES / fixture))
    fields = draw(rule_fields(layout, rule, int64=True))
    content = draw(st.one_of(st.none(), st.binary(max_size=16)))
    entities = []
    if parent:
        held = layout.rule(layout.rule(rule).parent)
        entities.append((held.name, {k: v for k, v in fields.items() if k in held.keys}, None))
    entities.append((rule, fields, content))
    return {"entities": entities, "victim": victim, "where": where, "how": how}


def check(session, plan, results):
    """Each element ended as configured, the other side of the clash is untouched, and the disk agrees."""
    layout = session.layout
    want = expected(layout, plan)
    assert [r.element.id for r in results] == [h.id for h in session.held]
    assert [r.outcome for r in results] == [outcome for outcome, _ in want], [r.reason for r in results]
    for (rule, fields, content), element, (outcome, final) in zip(plan["entities"], session.held, want, strict=True):
        record = _find(session.db, element.id)
        requested = full_fields(layout, layout.rule(rule), fields)
        if outcome in ("merged", "rekeyed"):
            assert not session.holding.has(element.id)
            assert (record.state, record.fields) == ("committed", final)
            assert record.requested == (requested if outcome == "rekeyed" else None)
            assert_on_disk(session, record, content)
        else:
            assert session.holding.has(element.id)
            if outcome == "blocked" or plan["where"] == "authority":
                assert record is None
            else:
                rollback = layout.rule(rule).links.active[0].rollback
                assert record.state == ("failed" if rollback else "out_of_sync")
    if session.competitor is not None:
        record = session.db.record(session.competitor.id)
        assert record.state == "committed"
        assert_on_disk(session, record, competing(plan["entities"][plan["victim"]][2]))
    elif plan["victim"] is not None:
        r, fields, content = plan["entities"][plan["victim"]]
        path = session.layout.real_path(session.layout.locate(r, fields))
        assert (path / ".entitylayout.json" if content is None else path).read_bytes() == FOREIGN


def assert_on_disk(session, record, content):
    path = session.layout.real_path(session.layout.locate(record.rule, record.fields))
    if record.content_hash is None:
        sidecar = path / ".entitylayout.json"
    else:
        assert path.read_bytes() == content
        sidecar = path.parent / f".{path.name}.entitylayout.json"
    stamp = read_sidecar(sidecar.read_text(encoding="utf-8"), str(sidecar))
    assert (stamp.id, stamp.body["fields"]) == (record.id, json.loads(canonical_json(record.fields)))


@pytest.mark.parametrize("case", CASES, ids=_case_id)
@settings(max_examples=3)
@given(data=st.data())
def test_replayed_offline_sessions_resolve_as_configured(case, data):
    fixture, rule, parent, victim, where, how = case
    plan = data.draw(offline_session(*case))
    entities = plan["entities"]
    assume(entities[-1][2] != FOREIGN)
    base = load_config_data(read_config(FIXTURES / fixture))
    clashing = base.rule(entities[victim if victim is not None else -1][0])
    if victim is not None:
        # Room for the next number in SQLite's 64-bit integers.
        for key in (clashing.version_key, clashing.suffix_key):
            assume(key is None or entities[victim][1].get(key, 0) < 2**62)
    layout = session_layout(fixture, clashing.name, where, how)

    clean = Session(layout, plan)
    results = clean.merge()
    check(clean, plan, results)
    settled = clean.state()
    steps = clean.steps
    # A settled session merged again, and copies of merged elements merged again, change nothing.
    again = clean.engine().merge()
    assert [r.outcome for r in again] == [r.outcome for r in results if r.outcome not in ("merged", "rekeyed")]
    for copy in clean.copies.iterdir():
        if not clean.holding.has(copy.name):
            shutil.copytree(copy, clean.holding.path / copy.name)
    clean.engine().merge()
    assert clean.state() == settled
    clean.close()

    # Crash at each step of the merge; the same claimant merges again and must end in the same place.
    for index, step in enumerate(steps):
        crashed = Session(layout, plan, {index: Crash})
        crashed.merge()
        assert crashed.state() == settled, step
        crashed.close()
