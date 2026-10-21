from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from entitylayout import (
    AUTHORITY_OPERATIONS,
    Backend,
    ConfigError,
    EntityExistsError,
    FilesystemBackend,
    InvalidValueError,
    LayoutError,
    MissingKeyError,
    OperationNotSupportedError,
    SQLiteBackend,
    TypedAttributes,
)

from conftest import load_fixture

SHOT = {"project": "alpha", "sequence": "ABC", "shot": 40}
MEDIA = [
    ({**SHOT, "version": 1, "camera": "main"}, {"status": "approved", "artist": "kim"}),
    ({**SHOT, "version": 2, "camera": "main"}, {"status": "wip", "artist": "kim"}),
    ({**SHOT, "version": 2, "camera": "main", "variant": "hero"}, {"status": "wip", "artist": "lee"}),
    ({**SHOT, "shot": 50, "version": 3, "camera": "main"}, {"status": "approved"}),
    ({"project": "beta", "sequence": "ABC", "shot": 40, "version": 1, "camera": "main"}, {}),
]


@pytest.fixture
def db():
    with SQLiteBackend(load_fixture("vfx"), ":memory:") as backend:
        for fields, attributes in MEDIA:
            backend.create("media", fields, attributes)
        backend.create("shot", SHOT)
        yield backend


def paths(entities):
    return [e.location.path for e in entities]


def test_operations_and_capabilities_are_published():
    assert SQLiteBackend.supported_operations() == {"query", "exists", "create", *AUTHORITY_OPERATIONS}
    assert SQLiteBackend.has_capability("attribute_queries")
    assert SQLiteBackend.has_capability("atomic_updates")
    assert not FilesystemBackend.has_capability("attribute_queries")
    with pytest.raises(LayoutError, match="unknown capability"):
        SQLiteBackend.has_capability("teleport")
    with pytest.raises(TypeError, match="unknown capabilities"):

        class Odd(Backend):
            capabilities = frozenset({"teleport"})


def test_create_returns_the_entity_with_an_fs_location(db):
    fields = {**SHOT, "version": 9, "camera": "main"}
    entity = db.create("media", fields, {"status": "wip"})
    assert entity.fields == fields
    assert entity.location == db.layout.locate("media", fields)
    assert entity.location.uri.startswith("fs://projects/")
    assert entity.attributes == {"status": "wip"}
    assert db.exists("media", fields)
    assert not db.exists("media", {**fields, "camera": "witness"})


def test_query_by_partial_fields(db):
    assert paths(db.query("media", {"project": "alpha", "shot": 40})) == [
        "alpha/shots/ABC/ABC_040/media/v001/main",
        "alpha/shots/ABC/ABC_040/media/v002/main",
        "alpha/shots/ABC/ABC_040/media/v002/main_hero",
    ]
    # Leaving out an optional key matches it being absent or present; naming it narrows the answer.
    assert len(db.query("media", {"camera": "main"})) == 5
    assert paths(db.query("media", {"variant": "hero"})) == ["alpha/shots/ABC/ABC_040/media/v002/main_hero"]


def test_rules_sharing_keys_stay_separate(db):
    assert [e.fields for e in db.query("shot")] == [SHOT]
    assert all(e.rule == "media" for e in db.query("media", SHOT))


def test_query_by_attributes(db):
    assert paths(db.query("media", {"shot": 40}, attributes={"status": "wip", "artist": "kim"})) == [
        "alpha/shots/ABC/ABC_040/media/v002/main"
    ]
    assert len(db.query("media", attributes={"status": "approved"})) == 2
    # An attribute a rule does not declare can still be stored and queried.
    db.create("media", {**SHOT, "version": 7, "camera": "main"}, {"reviewed": True, "score": 1.5})
    assert len(db.query("media", attributes={"reviewed": True})) == 1
    assert len(db.query("media", attributes={"score": 1.5})) == 1
    assert db.query("media", attributes={"score": "1.5"}) == []


def test_attribute_filters_only_test_scalars(db):
    for value in (None, ["a"], {"a": 1}):
        with pytest.raises(InvalidValueError, match="attribute filter 'status'"):
            db.query("media", attributes={"status": value})


def test_filesystem_refuses_attribute_filters(tmp_path):
    fs = FilesystemBackend(load_fixture("vfx").with_roots({"projects": tmp_path}))
    with pytest.raises(OperationNotSupportedError, match="attributes"):
        fs.query("media", attributes={"status": "wip"})


def test_create_refuses_duplicates_and_partial_fields(db):
    fields, _ = MEDIA[0]
    with pytest.raises(EntityExistsError, match="fs://projects/alpha/shots/ABC/ABC_040/media/v001/main"):
        db.create("media", fields)
    with pytest.raises(MissingKeyError):
        db.create("media", SHOT)
    with pytest.raises(LayoutError, match="no keys"):
        db.create("media", {**fields, "colour": "red"})
    with pytest.raises(LayoutError, match="are keys"):
        db.create("media", {**fields, "version": 8}, {"shot": 1})


def test_a_failed_transaction_writes_nothing(db):
    new = {**SHOT, "version": 8, "camera": "main"}
    with pytest.raises(EntityExistsError):
        with db.transaction():
            db.create("media", new)
            db.create("media", MEDIA[0][0])
    assert not db.exists("media", new)
    # A nested transaction rolls back on its own and leaves the outer one going.
    with db.transaction():
        db.create("media", new)
        with pytest.raises(EntityExistsError):
            with db.transaction():
                db.create("media", {**new, "version": 9})
                db.create("media", new)
    assert db.exists("media", new)
    assert not db.exists("media", {**new, "version": 9})


def test_integers_must_fit_in_64_bits(make_layout):
    layout = make_layout({"n": {"type": "int"}}, {"a": {"root": "r", "keys": ["n"], "templates": {"fs": "{n}"}}})
    with SQLiteBackend(layout, ":memory:") as db:
        db.create("a", {"n": 2**63 - 1})
        with pytest.raises(InvalidValueError, match="n: .* too large"):
            db.create("a", {"n": 2**63})
        with pytest.raises(InvalidValueError, match="too large"):
            db.query("a", {"n": -(2**63) - 1})


def test_declared_dates_round_trip(make_layout):
    layout = make_layout(
        {"name": {}, "day": {"type": "date"}},
        {
            "a": {
                "root": "r",
                "keys": ["name", "day"],
                "templates": {"fs": "{name}/{day}"},
                "attributes": {"due": "date", "seen": "datetime"},
            }
        },
    )
    due, seen = dt.date(2026, 10, 21), dt.datetime(2026, 10, 21, 9, 30)
    with SQLiteBackend(layout, ":memory:") as db:
        db.create("a", {"name": "x", "day": dt.date(2026, 1, 2)}, {"due": due, "seen": seen, "other": due})
        [entity] = db.query("a", {"day": dt.date(2026, 1, 2)}, attributes={"due": due})
        assert entity.fields == {"name": "x", "day": dt.date(2026, 1, 2)}
        # Undeclared dates are stored as ISO text and come back that way.
        assert entity.attributes == {"due": due, "seen": seen, "other": "2026-10-21"}
        with pytest.raises(LayoutError, match="'due' is declared date"):
            db.create("a", {"name": "y", "day": dt.date(2026, 1, 2)}, {"due": "soon"})
        assert not db.exists("a", {"name": "y", "day": dt.date(2026, 1, 2)})


def test_attributes_must_be_storable(db):
    for value in (float("nan"), object(), {1, 2}):
        with pytest.raises(InvalidValueError, match="attribute 'status' cannot be stored"):
            db.create("media", {**SHOT, "version": 8, "camera": "main"}, {"status": value})


def test_defaults_are_stored(make_layout):
    layout = make_layout(
        {"name": {}, "kind": {"default": "main"}},
        {"a": {"root": "r", "keys": ["name", "kind"], "templates": {"fs": "{name}_{kind}"}}},
    )
    with SQLiteBackend(layout, ":memory:") as db:
        assert db.create("a", {"name": "x"}).fields == {"name": "x", "kind": "main"}
        assert [e.fields for e in db.query("a", {"kind": "main"})] == [{"name": "x", "kind": "main"}]


def test_a_database_file_persists_and_follows_the_layout(tmp_path, make_layout):
    path = tmp_path / "entities.db"
    rules = {"a": {"root": "r", "keys": ["name"], "templates": {"fs": "{name}", "db": "a/{name}"}}}
    layout = make_layout({"name": {}}, rules)
    with SQLiteBackend(layout, path) as db:
        db.create("a", {"name": "x"})

    # A new key on reopening adds a column; existing rows still read back.
    grown = make_layout(
        {"name": {}, "n": {"type": "int"}},
        {**rules, "b": {"root": "r", "keys": ["name", "n"], "templates": {"fs": "{name}/{n}"}}},
    )
    with SQLiteBackend(grown, path) as db:
        assert [e.fields for e in db.query("a")] == [{"name": "x"}]
        db.create("b", {"name": "x", "n": 3})
        assert [e.location.uri for e in db.query("b")] == ["fs://r/x/3"]
        [(version,)] = db._conn.execute("SELECT config_version FROM entities WHERE rule = 'b'")
        assert version == "1"

    with pytest.raises(LayoutError, match="template 'fs', not 'db'"):
        SQLiteBackend(layout, path, "db")
    with SQLiteBackend(layout, tmp_path / "other.db", "db") as db:
        assert db.create("a", {"name": "x"}).location.uri == "db://r/a/x"


def test_rules_without_the_template_are_refused(make_layout):
    layout = make_layout({"name": {}}, {"a": {"root": "r", "keys": ["name"], "templates": {"object": "{name}"}}})
    with SQLiteBackend(layout, ":memory:") as db:
        with pytest.raises(LayoutError, match="no template for backend 'fs'"):
            db.create("a", {"name": "x"})
        with pytest.raises(LayoutError, match="no template for backend 'fs'"):
            db.query("a")


def test_keys_differing_only_in_case_are_refused(make_layout):
    layout = make_layout(
        {"name": {}, "Name": {}},
        {"a": {"root": "r", "keys": ["name", "Name"], "templates": {"fs": "{name}/{Name}"}}},
    )
    with pytest.raises(ConfigError, match="differ only in case"):
        SQLiteBackend(layout, ":memory:")


def test_rows_that_no_longer_fit_are_refused(db):
    db._conn.execute("UPDATE entities SET location = 'elsewhere' WHERE rule = 'shot'")
    with pytest.raises(LayoutError, match="stored location 'elsewhere' does not match"):
        db.query("shot")
    db._conn.execute("UPDATE entities SET location = 'alpha/shots/ABC/ABC_040', key_shot = 'forty' WHERE rule = 'shot'")
    with pytest.raises(LayoutError, match="does not fit rule 'shot'.*expected an integer"):
        db.query("shot")
    db._conn.execute("UPDATE entities SET attributes = '[1]' WHERE rule = 'media'")
    with pytest.raises(LayoutError, match="must be a JSON object"):
        db.query("media")


def test_a_file_that_is_not_a_database_is_refused(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("not a database, just some notes " * 10)
    with pytest.raises(LayoutError, match="cannot use SQLite database"):
        SQLiteBackend(load_fixture("vfx"), path)
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT)").connection.execute(
        "INSERT INTO meta VALUES ('schema', '99')"
    ).connection.commit()
    with pytest.raises(LayoutError, match="schema '99'"):
        SQLiteBackend(load_fixture("vfx"), other)


def test_the_optional_validator_checks_declared_types():
    layout = load_fixture("vfx")
    fields = {**SHOT, "version": 1, "camera": "main"}
    with SQLiteBackend(layout, ":memory:", validator=TypedAttributes()) as db:
        with pytest.raises(InvalidValueError, match="'status' must be a string"):
            db.create("media", fields, {"status": 3})
        with pytest.raises(InvalidValueError, match="'colour' is not declared"):
            db.create("media", fields, {"colour": "red"})
        assert db.create("media", fields, {"status": "wip", "artist": None}).attributes == {
            "status": "wip",
            "artist": None,
        }
    with SQLiteBackend(layout, ":memory:", validator=TypedAttributes(allow_undeclared=True)) as db:
        db.create("media", fields, {"colour": "red"})
    # Without a validator the core stores whatever it is given (decision 0005).
    with SQLiteBackend(layout, ":memory:") as db:
        assert db.create("media", fields, {"status": 3}).attributes == {"status": 3}


# Schema version 2: records with states, and the operation log


def _version_1_database(path):
    """A database as phase 3 wrote it, with two committed rows."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema', '1'), ('template', 'fs');
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, rule TEXT NOT NULL, location TEXT NOT NULL,
            config_version TEXT NOT NULL, attributes TEXT NOT NULL DEFAULT '{}', UNIQUE (rule, location));
        ALTER TABLE entities ADD COLUMN "key_project" TEXT;
        ALTER TABLE entities ADD COLUMN "key_sequence" TEXT;
        ALTER TABLE entities ADD COLUMN "key_shot" INTEGER;
        ALTER TABLE entities ADD COLUMN "key_retired" TEXT;
        INSERT INTO entities (id, rule, location, config_version, attributes, key_project, key_sequence, key_shot)
            VALUES ('one', 'shot', 'alpha/shots/ABC/ABC_040', '1', '{"note": "kept"}', 'alpha', 'ABC', 40),
                   ('two', 'shot', 'alpha/shots/ABC/ABC_050', '1', '{}', 'alpha', 'ABC', 50);
        """
    )
    conn.commit()
    conn.close()


def test_a_version_1_database_is_upgraded(tmp_path):
    path = tmp_path / "v1.db"
    _version_1_database(path)
    with SQLiteBackend(load_fixture("vfx"), path) as db:
        shots = db.query("shot")
        assert [(e.id, e.fields["shot"], e.attributes) for e in shots] == [
            ("one", 40, {"note": "kept"}),
            ("two", 50, {}),
        ]
        record = db.record("one")
        assert (record.state, record.revision, record.content_hash, record.lagging) == ("committed", 1, None, ())
        db.create("media", {**SHOT, "version": 1, "camera": "main"})
        with pytest.raises(EntityExistsError):
            db.create("shot", SHOT)
        columns = {row[1] for row in db._conn.execute("PRAGMA table_info(entities)")}
        # Columns for keys the layout no longer uses are kept, never dropped.
        assert {"key_retired", "state", "revision", "content_hash", "lagging", "key_version"} <= columns
    with SQLiteBackend(load_fixture("vfx"), path) as db:
        assert dict(db._conn.execute("SELECT name, value FROM meta"))["schema"] == "2"
        assert len(db.query("shot")) == 2


def test_pending_and_failed_records_are_hidden(db):
    fields = {**SHOT, "version": 8, "camera": "main"}
    record = db.reserve("media", fields, operation="op")
    assert record.state == "pending"
    assert not db.exists("media", fields)
    assert fields not in [e.fields for e in db.query("media")]
    # A pending record still holds its location.
    with pytest.raises(EntityExistsError):
        db.create("media", fields)
    db.settle("op", record.id, "failed")
    assert not db.exists("media", fields)
    # A failed one does not, and stays in the log.
    again = db.create("media", fields)
    assert again.id != record.id and db.exists("media", fields)
    assert [s.step for s in db.history(record.id)] == ["reserved", "failed"]
    assert db.record(record.id).state == "failed"


def test_out_of_sync_records_are_seen_with_their_lagging_links(db):
    fields = {**SHOT, "version": 8, "camera": "main"}
    record = db.reserve("media", fields, operation="op")
    db.settle("op", record.id, "out_of_sync", lagging=["files"])
    (found,) = db.query("media", {"version": 8})
    assert found.lagging == ("files",)
    assert [r.id for r in db.unsettled()] == [record.id]
    db.settle("op", record.id, "committed")
    assert db.unsettled() == []


def test_settle_refuses_moves_the_lifecycle_does_not_declare(db):
    record = db.reserve("media", {**SHOT, "version": 8, "camera": "main"}, operation="op")
    with pytest.raises(LayoutError, match="lagging links are given exactly"):
        db.settle("op", record.id, "out_of_sync")
    with pytest.raises(LayoutError, match="lagging links are given exactly"):
        db.settle("op", record.id, "committed", lagging=["files"])
    with pytest.raises(LayoutError, match="cannot move from pending to pending"):
        db.settle("op", record.id, "pending")
    db.settle("op", record.id, "committed")
    with pytest.raises(LayoutError, match="cannot move from committed to failed"):
        db.settle("op", record.id, "failed")
    with pytest.raises(LayoutError, match="no record nope"):
        db.record("nope")


def test_a_reservation_and_its_log_entry_commit_together(db):
    fields = {**SHOT, "version": 8, "camera": "main"}
    with pytest.raises(RuntimeError):
        with db.transaction():
            record = db.reserve("media", fields, operation="op")
            raise RuntimeError("crash")
    assert db.history(record.id) == []
    with pytest.raises(LayoutError):
        db.record(record.id)
