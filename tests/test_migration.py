"""The operations a migration script uses: rule claims, listing records with their logs, and restoring them."""

from __future__ import annotations

import dataclasses

import pytest

from entitylayout import (
    MIGRATION_OPERATIONS,
    Engine,
    EntityExistsError,
    FilesystemBackend,
    Holding,
    LayoutError,
    ReadOnlyError,
    RecordExistsError,
    SQLiteBackend,
    Step,
    UnreachableError,
    WriteRolledBackError,
    load_config_data,
    read_config,
)
from reference_migration import family, migrate
from test_engine import FRAME, MEDIA, SHOT, fail_at, tree
from test_sqlite import _version_1_database

from conftest import FIXTURES, load_fixture


def vfx(tmp_path, **authority):
    data = read_config(FIXTURES / "vfx")
    data["links"]["shot"]["tracking"] = {"role": "authority", **authority}
    (tmp_path / "projects").mkdir(exist_ok=True)
    return load_config_data(data).with_roots({"projects": tmp_path / "projects"})


@pytest.fixture
def env(tmp_path):
    """An old and a new authority, one file tree and a holding area."""
    layout = vfx(tmp_path, offline="hold")
    (tmp_path / "holding").mkdir()
    with SQLiteBackend(layout, tmp_path / "old.db") as old, SQLiteBackend(layout, tmp_path / "new.db") as new:

        def engine(authority, checkpoint=None):
            stores = {"tracking": authority, "files": FilesystemBackend(layout)}
            holding = Holding(layout, tmp_path / "holding", "laptop")
            return Engine(layout, stores, holding=holding, checkpoint=checkpoint, claimant="laptop")

        yield engine, old, new, tmp_path


def summary(db, rule):
    """Each record of rule with its log, without the sequence numbers each authority gives its own."""
    return [(r, [(s.operation, s.step, s.link, s.detail) for s in db.history(r.id)]) for r in db.records(rule)]


def test_sqlite_publishes_the_migration_operations():
    assert set(MIGRATION_OPERATIONS) <= SQLiteBackend.supported_operations()
    assert not set(MIGRATION_OPERATIONS) & FilesystemBackend.supported_operations()


def test_a_claimed_rule_cannot_be_written_but_can_be_read(env):
    engine, old, new, root = env
    shot = engine(old).create("shot", SHOT)
    pending = old.reserve("media", MEDIA, operation="op")
    assert old.claim_rule("media", "migration") and old.claim_rule("media", "migration")
    assert not old.claim_rule("media", "someone else")
    with pytest.raises(UnreachableError, match="rule 'media' is moving to another authority, claimed by 'migration'"):
        old.reserve("media", {**MEDIA, "version": 2}, operation="op2")
    with pytest.raises(UnreachableError):
        old.create("media", {**MEDIA, "version": 2})
    with pytest.raises(UnreachableError):
        old.log("op", pending.id, "item")
    with pytest.raises(UnreachableError):
        old.settle("op", pending.id, "committed")
    assert old.record(pending.id).state == "pending"
    assert [s.step for s in old.history(pending.id)] == ["reserved"]
    # Other rules, reads and record claims still work.
    old.log("op", shot.id, "note")
    assert old.query("shot")[0].id == shot.id and old.claim(pending.id, "laptop")
    old.release_rule("media", "someone else")
    assert old.claim_rule("media", "someone else") is False
    old.release_rule("media", None)
    assert old.settle("op", pending.id, "committed").state == "committed"
    with pytest.raises(LayoutError, match="no rule named 'nope'"):
        old.claim_rule("nope", "migration")


def test_records_lists_every_state_in_the_order_first_logged(env):
    engine, old, new, root = env
    first = engine(old).create("media", MEDIA)
    with pytest.raises(WriteRolledBackError) as caught:
        engine(old, fail_at("settle:committed")).create("media", {**MEDIA, "version": 2})
    pending = old.reserve("media", {**MEDIA, "version": 3}, operation="op")
    assert [(r.id, r.state) for r in old.records("media")] == [
        (first.id, "committed"),
        (caught.value.record.id, "failed"),
        (pending.id, "pending"),
    ]
    assert old.records("frame") == []


def test_rows_from_a_version_1_database_have_no_log_and_come_first(tmp_path):
    path = tmp_path / "v1.db"
    _version_1_database(path)
    with SQLiteBackend(load_fixture("vfx"), path) as old, SQLiteBackend(load_fixture("vfx"), ":memory:") as new:
        later = old.create("shot", {**SHOT, "shot": 30})
        assert [r.id for r in old.records("shot")] == ["one", "two", later.id]
        for record in old.records("shot"):
            new.restore(record, old.history(record.id))
        assert [r.id for r in new.records("shot")] == ["one", "two", later.id]
        assert new.history("one") == []


def test_restore_keeps_identity_state_and_log_and_running_it_again_changes_nothing(env):
    engine, old, new, root = env
    with pytest.raises(WriteRolledBackError):
        engine(old, fail_at("realize:files")).create("media", MEDIA)
    engine(old).create("media", MEDIA, {"status": "wip"})
    engine(old).create("frame", FRAME, content=b"pixels")
    old.reserve("media", {**MEDIA, "version": 3}, operation="op")
    before = tree(root / "projects")
    for _ in range(2):
        migrate(old, new, family(old.layout, "media"))
    for rule in ("shot", "media", "frame"):
        assert summary(new, rule) == summary(old, rule)
    assert tree(root / "projects") == before


def test_restore_refuses_a_record_that_differs(env):
    engine, old, new, root = env
    media = old.record(engine(old).create("media", MEDIA).id)
    history = old.history(media.id)
    new.restore(media, history)
    # A log that has grown since is the new authority's own work.
    new.log("later", media.id, "note")
    assert new.restore(media, history).id == media.id
    with pytest.raises(RecordExistsError, match="a log that does not start with the one being restored"):
        new.restore(media, [*history[:1], dataclasses.replace(history[1], step="other")])
    with pytest.raises(RecordExistsError, match="the same log but different fields"):
        new.restore(dataclasses.replace(media, revision=2), [*history, *new.history(media.id)[len(history) :]])
    stray = Step(1, "op", "another", "reserved")
    with pytest.raises(LayoutError, match=r"log entries \[1\] belong to other records"):
        new.restore(dataclasses.replace(media, id="x"), [stray])
    with pytest.raises(EntityExistsError, match="already exists"):
        new.restore(dataclasses.replace(media, id="x"), [])
    new.claim_rule("media", "elsewhere")
    with pytest.raises(UnreachableError):
        new.restore(dataclasses.replace(media, id="y", fields={**MEDIA, "version": 9}), [])


def test_a_tool_on_the_old_authority_holds_new_work_that_merges_into_the_new_one(env):
    engine, old, new, root = env
    shot = engine(old).create("shot", SHOT)
    migrate(old, new, family(old.layout, "shot"))
    held = engine(old).create("media", MEDIA)
    assert held.provisional and old.records("media") == []
    # Reads on the old authority still answer, with the held work overlaid.
    assert [e.id for e in engine(old).query("shot")] == [shot.id]
    assert [r.outcome for r in engine(old).merge()] == ["incomplete"]
    # The tool now points at the new authority.
    assert [(r.outcome, r.record.id) for r in engine(new).merge()] == [("merged", held.id)]
    assert old.records("media") == [] and new.record(held.id).state == "committed"


def test_a_tool_on_the_old_authority_follows_the_rules_offline_policy(tmp_path):
    for offline, error in (("read_only", ReadOnlyError), ("fail", UnreachableError)):
        layout = vfx(tmp_path, offline=offline)
        with SQLiteBackend(layout, ":memory:") as old, SQLiteBackend(layout, ":memory:") as new:
            engine = Engine(layout, {"tracking": old, "files": FilesystemBackend(layout)})
            migrate(old, new, family(layout, "shot"))
            with pytest.raises(error):
                engine.create("shot", SHOT)
            assert tree(tmp_path / "projects") == []


def test_a_migration_stops_on_a_rule_someone_else_claimed(env):
    engine, old, new, root = env
    old.claim_rule("frame", "someone else")
    with pytest.raises(LayoutError, match="rule 'frame' is claimed by someone else"):
        migrate(old, new, family(old.layout, "shot"))


def test_a_rekeyed_record_keeps_its_requested_key(tmp_path):
    data = read_config(FIXTURES / "vfx")
    data["links"]["media"] = {**data["links"]["shot"], "tracking": {"role": "authority", "clash": "version_up"}}
    data["links"]["frame"] = data["links"]["shot"]
    (tmp_path / "projects").mkdir()
    layout = load_config_data(data).with_roots({"projects": tmp_path / "projects"})
    with SQLiteBackend(layout, ":memory:") as old, SQLiteBackend(layout, ":memory:") as new:
        engine = Engine(layout, {"tracking": old, "files": FilesystemBackend(layout)})
        engine.create("media", MEDIA)
        rekeyed = old.record(engine.create("media", MEDIA).id)
        assert (rekeyed.fields["version"], rekeyed.requested["version"]) == (2, 1)
        migrate(old, new, family(layout, "media"))
        assert new.record(rekeyed.id) == rekeyed
