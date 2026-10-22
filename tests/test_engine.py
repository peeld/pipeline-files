from __future__ import annotations

import pytest

from entitylayout import (
    Backend,
    ClashError,
    ConfigError,
    Engine,
    EntityExistsError,
    FilesystemBackend,
    LayoutError,
    OperationNotSupportedError,
    OutOfSyncError,
    ReadOnlyError,
    SQLiteBackend,
    UnreachableError,
    WriteIncompleteError,
    WriteRolledBackError,
    load_config_data,
    read_config,
    read_sidecar,
)

from conftest import FIXTURES

SHOT = {"project": "alpha", "sequence": "ABC", "shot": 40}
MEDIA = {**SHOT, "version": 1, "camera": "main"}
FRAME = {**MEDIA, "frame": 1001, "ext": "exr"}
MEDIA_PATH = "alpha/shots/ABC/ABC_040/media/v001/main"


class Crash(BaseException):
    """Stands for the process dying: the engine has no chance to clean up."""


def fail_at(*names, error=RuntimeError):
    """A checkpoint that fails the named steps, each the first time it is reached."""
    pending = list(names)

    def checkpoint(step):
        if step in pending:
            pending.remove(step)
            raise error(f"injected failure at {step}")

    return checkpoint


def vfx(tmp_path, **changes):
    """The vfx layout with its root in tmp_path, and its links changed as given."""
    data = read_config(FIXTURES / "vfx")
    for name, settings in changes.items():
        data["links"]["shot"][name] = {**data["links"]["shot"].get(name, {}), **settings}
    return load_config_data(data).with_roots({"projects": tmp_path})


@pytest.fixture
def env(tmp_path):
    layout = vfx(tmp_path)
    with SQLiteBackend(layout, ":memory:") as db:
        stores = {"tracking": db, "files": FilesystemBackend(layout)}

        def engine(checkpoint=None, layout=layout):
            return Engine(layout, stores, checkpoint=checkpoint)

        yield engine, db, tmp_path


def tree(root):
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*"))


def test_a_create_commits_in_the_authority_and_the_link(env):
    engine, db, root = env
    entity = engine().create("media", MEDIA, {"status": "wip"})
    assert entity.id and entity.lagging == ()
    assert db.record(entity.id).state == "committed"
    assert (root / MEDIA_PATH).is_dir()
    sidecar = read_sidecar((root / MEDIA_PATH / ".entitylayout.json").read_text(), "test")
    assert (sidecar.id, sidecar.revision, sidecar.body["attributes"]) == (entity.id, 1, {"status": "wip"})
    assert not sidecar.edited and not sidecar.stale(1)
    assert [e.id for e in engine().query("media")] == [entity.id]
    assert [s.step for s in db.history(entity.id)] == [
        "reserved",
        *["item"] * 8,
        "realized",
        "committed",
    ]


def test_a_file_entity_is_written_with_its_hash(env):
    engine, db, root = env
    entity = engine().create("frame", FRAME, content=b"pixels")
    path = root / entity.location.path
    assert path.read_bytes() == b"pixels"
    record = db.record(entity.id)
    assert record.content_hash.startswith("sha256:")
    sidecar = read_sidecar((path.parent / f".{path.name}.entitylayout.json").read_text(), "test")
    assert sidecar.body["content_hash"] == record.content_hash
    # The parent media directory is made, but it is not a media entity.
    assert db.query("media") == []


def test_realize_is_idempotent(env):
    engine, db, root = env
    entity = engine().create("frame", FRAME, content=b"pixels")
    notes = []
    FilesystemBackend(db.layout).realize(db.record(entity.id), note=notes.append)
    assert notes == []


def test_a_hand_edited_sidecar_is_detected(env):
    engine, _, root = env
    engine().create("media", MEDIA)
    path = root / MEDIA_PATH / ".entitylayout.json"
    path.write_text(path.read_text().replace('"main"', '"witness"'))
    assert read_sidecar(path.read_text(), str(path)).edited
    with pytest.raises(LayoutError, match="not an entitylayout sidecar"):
        read_sidecar("{}", "x.json")


def test_a_failed_link_rolls_back_and_keeps_what_was_there(env):
    engine, db, root = env
    engine().create("shot", SHOT)
    before = tree(root)
    with pytest.raises(WriteRolledBackError, match="link 'files' failed.*marked failed") as caught:
        engine(fail_at("files:sidecar")).create("media", MEDIA)
    assert caught.value.record.state == "failed"
    assert tree(root) == before
    assert engine().query("media") == []
    # A failed record does not hold its location.
    assert engine().create("media", MEDIA).fields == MEDIA


def test_without_rollback_a_failed_link_leaves_the_record_out_of_sync(env, tmp_path):
    engine, db, root = env
    layout = vfx(tmp_path, files={"rollback": False})
    with pytest.raises(OutOfSyncError, match=r"\['files'\] behind") as caught:
        engine(fail_at("realized:files"), layout=layout).create("media", MEDIA)
    record = caught.value.record
    assert (record.state, record.lagging) == ("out_of_sync", ("files",))
    # Out of sync records are seen, with the lagging link shown.
    assert [e.lagging for e in engine(layout=layout).query("media")] == [("files",)]
    assert [r.state for r in engine(layout=layout).recover()] == ["committed"]
    assert engine(layout=layout).query("media")[0].lagging == ()


def test_a_retry_that_fails_again_stays_out_of_sync(env, tmp_path):
    engine, db, root = env
    layout = vfx(tmp_path, files={"rollback": False})
    with pytest.raises(OutOfSyncError):
        engine(fail_at("files:dir"), layout=layout).create("media", MEDIA)
    assert [r.state for r in engine(fail_at("files:sidecar"), layout=layout).recover()] == ["out_of_sync"]
    assert [r.state for r in engine(layout=layout).recover()] == ["committed"]
    assert (root / MEDIA_PATH / ".entitylayout.json").is_file()


def test_an_undo_that_would_remove_other_work_leaves_the_record_out_of_sync(env):
    engine, db, root = env

    def checkpoint(step):
        if step == "realized:files":
            (root / MEDIA_PATH / "someone_elses.txt").write_text("keep me")
            raise RuntimeError("link failed")

    with pytest.raises(OutOfSyncError, match="could not be undone") as caught:
        engine(checkpoint).create("media", MEDIA)
    assert caught.value.record.state == "out_of_sync"
    assert (root / MEDIA_PATH / "someone_elses.txt").read_text() == "keep me"


def test_a_failed_commit_rolls_back(env):
    engine, db, root = env
    with pytest.raises(WriteRolledBackError, match="the commit failed") as caught:
        engine(fail_at("settle:committed")).create("media", MEDIA)
    assert caught.value.record.state == "failed"
    assert tree(root) == []


def test_a_failed_commit_with_rollback_off_is_left_for_recovery_to_commit(env, tmp_path):
    engine, db, root = env
    layout = vfx(tmp_path, files={"rollback": False})
    with pytest.raises(WriteIncompleteError, match="rollback off") as caught:
        engine(fail_at("settle:committed"), layout=layout).create("media", MEDIA)
    assert caught.value.record.state == "pending"
    assert (root / MEDIA_PATH).is_dir()
    assert [r.state for r in engine(layout=layout).recover()] == ["committed"]


def test_a_settle_that_fails_leaves_the_record_pending_for_recovery(env):
    engine, db, root = env
    with pytest.raises(WriteIncompleteError, match="left pending") as caught:
        engine(fail_at("files:dir", "settle:failed")).create("media", MEDIA)
    assert caught.value.record.state == "pending"
    assert engine().query("media") == []
    assert [r.state for r in engine().recover()] == ["failed"]
    assert tree(root) == []


def test_a_crash_mid_link_is_finished_by_recovery(env):
    engine, db, root = env
    with pytest.raises(Crash):
        engine(fail_at("files:sidecar", error=Crash)).create("media", MEDIA)
    (pending,) = db.unsettled()
    assert pending.state == "pending"
    assert engine().query("media") == []
    assert [r.state for r in engine().recover()] == ["committed"]
    assert [e.fields for e in engine().query("media")] == [MEDIA]
    assert engine().recover() == []


def test_a_crash_during_rollback_is_undone_by_recovery(env):
    engine, db, root = env

    def checkpoint(step):
        if step == "files:sidecar":
            raise RuntimeError("link failed")
        if step == "undo:files":
            raise Crash()

    with pytest.raises(Crash):
        engine(checkpoint).create("media", MEDIA)
    (pending,) = db.unsettled()
    assert pending.state == "pending" and tree(root)
    assert [r.state for r in engine().recover()] == ["failed"]
    assert tree(root) == []


def test_a_crash_before_recovery_of_a_file_entity_without_content_rolls_back(env):
    engine, db, root = env
    with pytest.raises(Crash):
        engine(fail_at("files:file", error=Crash)).create("frame", FRAME, content=b"pixels")
    # The content was never stored, so recovery cannot finish the write and undoes it.
    assert [r.state for r in engine().recover()] == ["failed"]
    assert tree(root) == []


def test_a_file_with_different_content_is_a_clash(env):
    engine, db, root = env
    path = root / "alpha/shots/ABC/ABC_040/media/v001/main/ABC_040_v001.1001.exr"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"someone else's pixels")
    with pytest.raises(WriteRolledBackError) as caught:
        engine().create("frame", FRAME, content=b"pixels")
    assert isinstance(caught.value.__cause__, ClashError)
    assert path.read_bytes() == b"someone else's pixels"
    # The same content already there is not a clash.
    path.write_bytes(b"pixels")
    assert engine().create("frame", FRAME, content=b"pixels").id


def test_the_authority_refuses_a_taken_key_and_touches_nothing(env):
    engine, db, root = env
    engine().create("media", MEDIA)
    before = tree(root)
    with pytest.raises(EntityExistsError):
        engine().create("media", MEDIA)
    assert tree(root) == before
    with pytest.raises(RuntimeError):
        engine(fail_at("reserve")).create("media", {**MEDIA, "version": 2})
    assert tree(root) == before and len(engine().query("media")) == 1


def test_offline_policies(env, tmp_path):
    engine, db, root = env
    engine().create("media", MEDIA)
    with pytest.raises(UnreachableError):
        engine(fail_at("reserve", error=UnreachableError)).create("media", {**MEDIA, "version": 2})
    layout = vfx(tmp_path, tracking={"offline": "read_only"})
    with pytest.raises(ReadOnlyError, match="read_only"):
        engine(fail_at("reserve", error=UnreachableError), layout=layout).create("media", {**MEDIA, "version": 2})
    assert len(engine().query("media")) == 1


def test_read_only_queries_fall_back_to_an_active_link(tmp_path):
    layout = vfx(tmp_path, tracking={"offline": "read_only"})

    class Down(SQLiteBackend):
        def query(self, *args, **kwargs):
            raise UnreachableError("tracking database is down")

    with Down(layout, ":memory:") as db:
        engine = Engine(layout, {"tracking": db, "files": FilesystemBackend(layout)})
        engine.create("media", MEDIA)
        (found,) = engine.query("media")
        assert found.location.path == MEDIA_PATH and found.id is None
        strict = Engine(vfx(tmp_path), {"tracking": db, "files": FilesystemBackend(layout)})
        with pytest.raises(UnreachableError):
            strict.query("media")


def test_active_links_run_in_order_and_a_later_failure_undoes_earlier_ones(tmp_path):
    data = read_config(FIXTURES / "vfx")
    data["links"]["shot"] = {
        "tracking": {"role": "authority"},
        "mirror": {"role": "active", "order": 2},
        "files": {"role": "active", "order": 1},
    }
    layout = load_config_data(data)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    steps = []

    def checkpoint(step):
        steps.append(step)
        if step == "mirror:sidecar":
            raise RuntimeError("mirror is full")

    with SQLiteBackend(layout, ":memory:") as db:
        stores = {
            "tracking": db,
            "files": FilesystemBackend(layout.with_roots({"projects": tmp_path / "a"})),
            "mirror": FilesystemBackend(layout.with_roots({"projects": tmp_path / "b"})),
        }
        with pytest.raises(WriteRolledBackError, match="'mirror' failed"):
            Engine(layout, stores, checkpoint=checkpoint).create("shot", SHOT)
    starts = [s for s in steps if s.startswith(("realize:", "undo:"))]
    assert starts == ["realize:files", "realize:mirror", "undo:mirror", "undo:files"]
    assert tree(tmp_path) == ["a", "b"]


def test_the_engine_refuses_bindings_and_settings_it_cannot_carry_out(tmp_path):
    layout = vfx(tmp_path)
    with SQLiteBackend(layout, ":memory:") as db:
        fs = FilesystemBackend(layout)
        with pytest.raises(ConfigError, match="'files' is not bound"):
            Engine(layout, {"tracking": db})
        with pytest.raises(OperationNotSupportedError, match="cannot be the authority link 'tracking'"):
            Engine(layout, {"tracking": fs, "files": FilesystemBackend(layout)})
        with pytest.raises(OperationNotSupportedError, match="cannot be the active link 'files'"):
            Engine(layout, {"tracking": db, "files": SQLiteBackend(layout, ":memory:")})
        with pytest.raises(ConfigError, match="more than one of its links"):
            Engine(layout, {"tracking": db, "files": db})
        with pytest.raises(ConfigError, match="needs a version_key"):
            vfx(tmp_path, files={"clash": "version_up"})
        with pytest.raises(ConfigError, match="needs a holding area"):
            Engine(vfx(tmp_path, tracking={"offline": "hold"}), {"tracking": db, "files": fs})

        class NoProbe(FilesystemBackend):
            clash = Backend.clash

        data = read_config(FIXTURES / "vfx")
        data["links"]["media"] = {"tracking": {"role": "authority"}, "files": {"role": "active", "clash": "version_up"}}
        data["links"]["frame"] = {"tracking": {"role": "authority"}, "files": {"role": "active"}}
        with pytest.raises(OperationNotSupportedError, match=r"lacks \['clash'\]"):
            Engine(load_config_data(data), {"tracking": db, "files": NoProbe(layout)})
        # Passive links run only on triggers, so they need no backend yet.
        engine = Engine(layout, {"tracking": db, "files": fs})
    data = read_config(FIXTURES / "vfx")
    del data["links"]
    with pytest.raises(ConfigError, match="has no links"):
        Engine(load_config_data(data), {}).create("shot", SHOT)
    assert repr(engine) == "Engine(['files', 'tracking'])"
