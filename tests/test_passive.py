"""Passive links: one call realizes a committed record in them, outside the commit (decision 0019)."""

from __future__ import annotations

import pytest

from entitylayout import (
    ConfigError,
    Engine,
    FilesystemBackend,
    LayoutError,
    OperationNotSupportedError,
    SQLiteBackend,
    WriteRolledBackError,
    load_config_data,
    read_config,
    read_sidecar,
)
from test_engine import FRAME, MEDIA, MEDIA_PATH, SHOT, Crash, fail_at, tree

from conftest import FIXTURES


def vfx(tmp_path, **links):
    """The vfx layout with its root in tmp_path/projects, and the shot's links changed or added as given."""
    data = read_config(FIXTURES / "vfx")
    for name, settings in links.items():
        data["links"]["shot"][name] = {**data["links"]["shot"].get(name, {}), **settings}
    (tmp_path / "projects").mkdir(exist_ok=True)
    return load_config_data(data).with_roots({"projects": tmp_path / "projects"})


def archive(layout, path):
    """A filesystem store with the projects root at path, for a passive link."""
    path.mkdir(exist_ok=True)
    return FilesystemBackend(layout.with_roots({"projects": path}))


@pytest.fixture
def env(tmp_path):
    layout = vfx(tmp_path)
    with SQLiteBackend(layout, ":memory:") as db:
        stores = {"tracking": db, "files": FilesystemBackend(layout), "review": archive(layout, tmp_path / "review")}

        def engine(checkpoint=None, layout=layout, **extra):
            return Engine(layout, {**stores, **extra}, checkpoint=checkpoint)

        yield engine, db, tmp_path


def test_an_event_realizes_a_committed_record_in_the_links_it_triggers(env):
    engine, db, root = env
    media = engine().create("media", MEDIA)
    steps = []
    results = engine(steps.append).realize_passive("media", media.id, event="approved")
    assert [(r.link, r.realized, r.error) for r in results] == [("review", True, None)]
    sidecar = read_sidecar((root / "review" / MEDIA_PATH / ".entitylayout.json").read_text(), "test")
    assert sidecar.id == media.id
    assert steps[:2] == ["passive:review", "realize:review"] and steps[-1] == "realized:review"
    # The run is logged in the authority as its own operation, and the record is unchanged.
    passive = [s for s in db.history(media.id) if s.link == "review"]
    assert [s.step for s in passive] == ["passive", *["item"] * 8, "realized"]
    assert passive[0].detail == {"event": "approved"} and len({s.operation for s in passive}) == 1
    assert db.record(media.id).state == "committed"


def test_a_link_is_realized_by_name_and_running_it_again_changes_nothing(env):
    engine, db, root = env
    frame = engine().create("frame", FRAME, content=b"pixels")
    assert engine().realize_passive("frame", frame.id, link="review", content=b"pixels")[0].realized
    before = tree(root / "review")
    assert (root / "review" / frame.location.path).read_bytes() == b"pixels"
    # Already there, so the content is not needed again.
    assert engine().realize_passive("frame", frame.id, link="review")[0].realized
    assert tree(root / "review") == before


def test_a_failure_is_reported_and_the_next_link_still_runs(env, tmp_path):
    engine, db, root = env
    layout = vfx(tmp_path, backup={"role": "passive", "triggers": ["approved"]})
    backup = archive(layout, tmp_path / "backup")
    frame = engine(layout=layout, backup=backup).create("frame", FRAME, content=b"pixels")
    # Without the content, a file cannot be copied.
    results = engine(layout=layout, backup=backup).realize_passive("frame", frame.id, event="approved")
    assert [r.link for r in results] == ["review", "backup"]
    assert all(isinstance(r.error, LayoutError) and "content was not given" in str(r.error) for r in results)
    results = engine(fail_at("realize:review"), layout=layout, backup=backup).realize_passive(
        "frame", frame.id, event="approved", content=b"pixels"
    )
    assert [(r.link, r.realized) for r in results] == [("review", False), ("backup", True)]
    assert "injected failure at realize:review" in str(results[0].error)
    # The record is never touched by a passive link.
    assert db.record(frame.id).state == "committed" and db.record(frame.id).lagging == ()


def test_a_crash_leaves_logged_items_and_a_later_call_finishes(env):
    engine, db, root = env
    media = engine().create("media", MEDIA)
    with pytest.raises(Crash):
        engine(fail_at("review:sidecar", error=Crash)).realize_passive("media", media.id, event="approved")
    assert (root / "review" / MEDIA_PATH).is_dir()
    assert not (root / "review" / MEDIA_PATH / ".entitylayout.json").exists()
    # Nothing retries it on its own: recovery leaves a committed record alone.
    assert engine().recover() == []
    assert engine().realize_passive("media", media.id, event="approved")[0].realized
    assert (root / "review" / MEDIA_PATH / ".entitylayout.json").is_file()


def test_only_committed_records_are_realized(env, tmp_path):
    engine, db, root = env
    with pytest.raises(WriteRolledBackError) as caught:
        engine(fail_at("settle:committed")).create("media", MEDIA)
    with pytest.raises(LayoutError, match="is failed, so its passive links wait"):
        engine().realize_passive("media", caught.value.record.id, event="approved")
    shot = engine().create("shot", SHOT)
    with pytest.raises(LayoutError, match="is of rule 'shot', not 'media'"):
        engine().realize_passive("media", shot.id, event="approved")
    assert tree(root / "review") == []


def test_the_links_to_run_are_checked_before_any_runs(env, tmp_path):
    engine, db, root = env
    media = engine().create("media", MEDIA)
    with pytest.raises(LayoutError, match="exactly one of link= or event="):
        engine().realize_passive("media", media.id)
    with pytest.raises(LayoutError, match="exactly one of link= or event="):
        engine().realize_passive("media", media.id, link="review", event="approved")
    with pytest.raises(ConfigError, match=r"no passive link 'files'; its passive links are \['review'\]"):
        engine().realize_passive("media", media.id, link="files")
    with pytest.raises(ConfigError, match=r"no rule has a passive link triggered by 'aproved'"):
        engine().realize_passive("media", media.id, event="aproved")
    unbound = Engine(engine().layout, {"tracking": db, "files": FilesystemBackend(engine().layout)})
    with pytest.raises(ConfigError, match=r"passive links \['review'\] are not bound"):
        unbound.realize_passive("media", media.id, event="approved")
    assert tree(root / "review") == []


def test_an_event_this_rule_does_not_name_runs_nothing(tmp_path):
    data = read_config(FIXTURES / "vfx")
    data["links"]["media"] = {"tracking": {"role": "authority"}, "files": {"role": "active"}}
    (tmp_path / "projects").mkdir()
    layout = load_config_data(data).with_roots({"projects": tmp_path / "projects"})
    with SQLiteBackend(layout, ":memory:") as db:
        engine = Engine(layout, {"tracking": db, "files": FilesystemBackend(layout)})
        media = engine.create("media", MEDIA)
        assert engine.realize_passive("media", media.id, event="approved") == []


def test_a_passive_binding_the_engine_cannot_carry_out_is_refused(env, tmp_path):
    engine, db, root = env
    with pytest.raises(ConfigError, match="passive link 'review' has clash rule 'suffix'"):
        engine(layout=vfx(tmp_path, review={"clash": "suffix"}))
    # Left unbound, it is never run, so it is not refused.
    layout = vfx(tmp_path, review={"clash": "suffix"})
    Engine(layout, {"tracking": db, "files": FilesystemBackend(layout)})
    with SQLiteBackend(engine().layout, ":memory:") as other:
        with pytest.raises(OperationNotSupportedError, match=r"passive link 'review'; it lacks \['realize'\]"):
            engine(review=other)
    files = FilesystemBackend(engine().layout)
    with pytest.raises(ConfigError, match="one backend is bound to more than one of its links"):
        engine(files=files, review=files)
