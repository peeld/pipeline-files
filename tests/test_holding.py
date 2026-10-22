"""Holding and merge: offline creates, the owner's overlay, claims, clash rules and dependency order."""

from __future__ import annotations

import datetime as dt
import json
import shutil

import pytest

from entitylayout import (
    ClashError,
    ConfigError,
    Engine,
    EntityExistsError,
    FilesystemBackend,
    Holding,
    HoldingError,
    SQLiteBackend,
    UnreachableError,
    load_config_data,
    read_config,
)

from conftest import FIXTURES

SHOT = {"project": "alpha", "sequence": "ABC", "shot": 40}
MEDIA = {**SHOT, "version": 1, "camera": "main"}
FRAME = {**MEDIA, "frame": 1001, "ext": "exr"}
MEDIA_PATH = "alpha/shots/ABC/ABC_040/media/v001/main"
# Media versions up on a clash. Frames have no version key of their own, so they keep the shot's links.
MEDIA_VERSION_UP = {"media": {"tracking": {"clash": "version_up"}, "files": {}}, "frame": {"tracking": {}, "files": {}}}


class Switchable(SQLiteBackend):
    """An authority that can be taken offline: reserving and querying fail while it is down."""

    down = False

    def reserve(self, *args, **kwargs):
        if self.down:
            raise UnreachableError("tracking database is down")
        return super().reserve(*args, **kwargs)

    def query(self, *args, **kwargs):
        if self.down:
            raise UnreachableError("tracking database is down")
        return super().query(*args, **kwargs)


def vfx(tmp_path, links=None, **authority):
    """The vfx layout with holding on, and the authority settings and per-rule links given."""
    data = read_config(FIXTURES / "vfx")
    data["links"]["shot"]["tracking"] = {"role": "authority", "offline": "hold", **authority}
    for rule, changes in (links or {}).items():
        data["links"][rule] = {name: {**data["links"]["shot"].get(name, {}), **s} for name, s in changes.items()}
    root = tmp_path / "projects"
    root.mkdir(exist_ok=True)
    return load_config_data(data).with_roots({"projects": root})


@pytest.fixture
def env(tmp_path):
    """Build engines that share one authority, one file tree and one holding area."""
    (tmp_path / "holding").mkdir()
    made = {}

    def engine(layout=None, owner="laptop", checkpoint=None, claimant=None):
        layout = layout or made.get("layout") or vfx(tmp_path)
        if "db" not in made:
            made["layout"] = layout
            made["db"] = Switchable(layout, ":memory:")
        stores = {"tracking": made["db"], "files": FilesystemBackend(layout)}
        holding = Holding(layout, tmp_path / "holding", owner)
        return Engine(layout, stores, holding=holding, checkpoint=checkpoint, claimant=claimant)

    yield engine, made, tmp_path
    if "db" in made:
        made["db"].close()


def offline(made):
    made["db"].down = True


def online(made):
    made["db"].down = False


def outcomes(results):
    return [(r.element.rule, r.outcome) for r in results]


def test_a_create_while_the_authority_is_down_is_held(env):
    engine, made, root = env
    e = engine()
    offline(made)
    held = e.create("media", MEDIA, {"status": "wip"})
    assert held.provisional and held.id and held.location.path == MEDIA_PATH
    assert not (root / "projects" / MEDIA_PATH).exists()
    (element,) = e.holding.elements()
    assert (element.id, element.owner, element.sequence, element.parent) == (held.id, "laptop", 1, None)
    manifest = json.loads((element.path / "manifest.json").read_text())
    assert manifest["fields"] == {**MEDIA}
    # The owner sees it overlaid, from the active link while the authority is down.
    assert [(x.id, x.provisional) for x in e.query("media")] == [(held.id, True)]
    # Another machine does not.
    assert engine(owner="desktop").query("media") == []
    with pytest.raises(EntityExistsError, match="held element"):
        e.create("media", MEDIA)
    online(made)
    assert [x.id for x in e.query("media", {"camera": "main"}, attributes={"status": "wip"})] == [held.id]
    assert e.query("media", {"camera": "witness"}) == []


def test_a_merge_writes_the_element_under_its_uuid_and_removes_it(env):
    engine, made, root = env
    e = engine()
    offline(made)
    held = e.create("frame", FRAME, content=b"pixels")
    online(made)
    (result,) = e.merge()
    assert result.outcome == "merged" and result.record.id == held.id
    assert result.record.state == "committed" and result.record.requested is None
    assert (root / "projects" / MEDIA_PATH / "ABC_040_v001.1001.exr").read_bytes() == b"pixels"
    assert e.holding.elements() == [] and list((root / "holding").iterdir()) == []
    assert [(x.id, x.provisional) for x in e.query("frame")] == [(held.id, False)]
    assert e.merge() == []


def test_a_merge_is_idempotent_by_internal_id(env):
    engine, made, root = env
    e = engine()
    offline(made)
    held = e.create("media", MEDIA)
    copy = root / "copy"
    shutil.copytree(e.holding.path / held.id, copy)
    online(made)
    assert outcomes(e.merge()) == [("media", "merged")]
    # The same element merged again, from a copy, is recognized by its ID.
    shutil.copytree(copy, e.holding.path / held.id)
    (again,) = e.merge()
    assert (again.outcome, again.record.id) == ("merged", held.id)
    assert len(e.query("media")) == 1 and e.holding.elements() == []


def test_a_clash_under_fail_needs_a_decision_and_a_person_can_retarget(env):
    engine, made, root = env
    e = engine()
    offline(made)
    held = e.create("media", MEDIA)
    online(made)
    other = engine(owner="desktop").create("media", MEDIA)
    (result,) = e.merge()
    assert result.outcome == "needs_decision" and "already exists" in result.reason
    assert [x.id for x in e.query("media") if not x.provisional] == [other.id]
    # The element is never deleted by the merge; a person decides.
    e.holding.retarget(held.id, {**MEDIA, "camera": "witness"})
    (result,) = e.merge()
    assert (result.outcome, result.record.fields["camera"]) == ("merged", "witness")


def test_version_up_at_the_authority_keeps_the_requested_key(env, tmp_path):
    engine, made, root = env
    layout = vfx(tmp_path, links=MEDIA_VERSION_UP)
    e = engine(layout)
    offline(made)
    held = e.create("media", MEDIA)
    online(made)
    e.create("media", MEDIA)
    e.create("media", {**MEDIA, "version": 4})
    (result,) = e.merge()
    assert result.outcome == "rekeyed"
    assert (result.record.fields["version"], result.record.requested["version"]) == (5, 1)
    assert made["db"].record(held.id).requested == {**MEDIA}
    # Online creates follow the same rule.
    assert e.create("media", MEDIA).fields["version"] == 6


def test_suffix_finds_the_next_free_number(tmp_path):
    data = read_config(FIXTURES / "office")
    data["links"]["deliverable"]["dms"] = {"role": "authority", "clash": "suffix"}
    root = tmp_path / "clients"
    root.mkdir()
    layout = load_config_data(data).with_roots({"clients": root})
    fields = {"client": "Acme Ltd", "year": 2026, "quarter": 1, "doctype": "report", "ext": "docx"}
    with SQLiteBackend(layout, ":memory:") as db:
        engine = Engine(layout, {"dms": db, "drive": FilesystemBackend(layout)})
        names = [engine.create("deliverable", fields, content=b"x").location.path.rsplit("/", 1)[1] for _ in range(3)]
    assert names == [f"Acme Ltd 2026 Q1 report{suffix}.docx" for suffix in ("", " (2)", " (3)")]


def test_a_clash_an_active_link_finds_follows_that_links_rule(env, tmp_path):
    engine, made, root = env
    layout = vfx(tmp_path, links={**MEDIA_VERSION_UP, "media": {"tracking": {}, "files": {"clash": "version_up"}}})
    e = engine(layout)
    # Someone else's work sits where version 1 would go, unknown to the authority.
    foreign = root / "projects" / MEDIA_PATH
    foreign.mkdir(parents=True)
    (foreign / ".entitylayout.json").write_text("{}")
    entity = e.create("media", MEDIA)
    assert entity.fields["version"] == 2
    assert (foreign / ".entitylayout.json").read_text() == "{}"


def test_a_child_waits_for_its_held_parent_and_follows_its_final_key(env, tmp_path):
    engine, made, root = env
    layout = vfx(tmp_path, links=MEDIA_VERSION_UP)
    e = engine(layout)
    offline(made)
    media = e.create("media", MEDIA)
    frame = e.create("frame", FRAME, content=b"pixels")
    (_, held_frame) = e.holding.elements()
    assert held_frame.parent == media.id
    online(made)
    e.create("media", MEDIA)
    assert outcomes(e.merge()) == [("media", "rekeyed"), ("frame", "rekeyed")]
    record = made["db"].record(frame.id)
    assert (record.fields["version"], record.requested["version"]) == (2, 1)
    assert (root / "projects" / "alpha/shots/ABC/ABC_040/media/v002/main/ABC_040_v002.1001.exr").is_file()


def test_a_child_is_blocked_while_its_parent_needs_a_decision(env):
    engine, made, root = env
    e = engine()
    offline(made)
    media = e.create("media", MEDIA)
    e.create("frame", FRAME, content=b"pixels")
    online(made)
    engine(owner="desktop").create("media", MEDIA)
    results = e.merge()
    assert outcomes(results) == [("media", "needs_decision"), ("frame", "blocked")]
    assert media.id in results[1].reason
    # A person may discard held work, but not a parent before its children.
    with pytest.raises(HoldingError, match="parent of"):
        e.holding.discard(media.id)


def test_merge_on_confirm_and_the_age_limit(env, tmp_path):
    engine, made, root = env
    e = engine(vfx(tmp_path, merge="confirm"))
    offline(made)
    held = e.create("media", MEDIA)
    online(made)
    (result,) = e.merge()
    assert result.outcome == "awaiting_confirmation" and "confirms" in result.reason
    assert outcomes(e.merge(confirm=[held.id])) == [("media", "merged")]

    aged = engine(vfx(tmp_path, max_age="7d"))
    offline(made)
    held = aged.create("media", {**MEDIA, "version": 2})
    online(made)
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=8)
    (result,) = aged.merge(now=later)
    assert result.outcome == "awaiting_confirmation" and "max_age" in result.reason
    assert outcomes(aged.merge(now=later - dt.timedelta(days=2))) == [("media", "merged")]


def test_claims_keep_two_mergers_apart(env):
    engine, made, root = env
    e = engine()
    offline(made)
    held = e.create("media", MEDIA)
    online(made)
    (element,) = e.holding.elements()
    assert e.holding.claim(element, "someone else")
    (result,) = e.merge()
    assert result.outcome == "claimed" and "someone else" in result.reason
    # Adopting another owner's work is explicit, and a person may break a stale claim.
    e.holding.release(element, None)
    assert outcomes(engine(owner="desktop").merge()) == []
    assert outcomes(engine(owner="desktop").merge(adopt=["laptop"])) == [("media", "merged")]
    assert made["db"].record(held.id).state == "committed"


def test_a_merge_that_crashes_is_finished_by_the_same_claimant(env):
    engine, made, root = env

    class Crash(BaseException):
        pass

    def crash_at(name):
        def checkpoint(step):
            if step == name:
                raise Crash()

        return checkpoint

    e = engine()
    offline(made)
    held = e.create("frame", FRAME, content=b"pixels")
    online(made)
    with pytest.raises(Crash):
        engine(checkpoint=crash_at("files:file"), claimant="laptop").merge()
    assert made["db"].record(held.id).state == "pending"
    # A different claimant leaves it alone; the same one, after a restart, finishes it with the held content.
    assert outcomes(engine(claimant="other").merge()) == [("frame", "claimed")]
    assert outcomes(engine(claimant="laptop").merge()) == [("frame", "merged")]
    assert (root / "projects" / MEDIA_PATH / "ABC_040_v001.1001.exr").read_bytes() == b"pixels"


def test_a_merge_after_a_rollback_reserves_the_same_id_again(env):
    engine, made, root = env

    def fail_once(step):
        if step == "files:sidecar":
            raise RuntimeError("file server full")

    e = engine()
    offline(made)
    held = e.create("media", MEDIA)
    online(made)
    (result,) = engine(checkpoint=fail_once).merge()
    assert (result.outcome, result.record.state) == ("incomplete", "failed")
    assert not (root / "projects" / MEDIA_PATH).exists()
    (result,) = e.merge()
    assert (result.outcome, result.record.id, result.record.state) == ("merged", held.id, "committed")
    steps = [s.step for s in made["db"].history(held.id)]
    assert steps.count("reserved") == 2 and steps[-1] == "committed"


def test_recovery_skips_records_another_claimant_holds(env):
    engine, made, root = env
    e = engine()

    class Crash(BaseException):
        pass

    def crash(step):
        if step == "files:sidecar":
            raise Crash()

    with pytest.raises(Crash):
        engine(checkpoint=crash).create("media", MEDIA)
    (pending,) = made["db"].unsettled()
    assert made["db"].claim(pending.id, "another recovery")
    assert e.recover() == []
    assert made["db"].record(pending.id).state == "pending"
    e.release("media", pending.id)
    assert [r.state for r in e.recover()] == ["committed"]


def test_the_engine_needs_a_holding_area_for_hold(tmp_path):
    layout = vfx(tmp_path)
    with SQLiteBackend(layout, ":memory:") as db:
        stores = {"tracking": db, "files": FilesystemBackend(layout)}
        with pytest.raises(ConfigError, match="needs a holding area"):
            Engine(layout, stores)
        with pytest.raises(ConfigError, match="no holding area"):
            Engine(load_config_data(read_config(FIXTURES / "vfx")), stores).merge()
    with pytest.raises(HoldingError, match="not a directory"):
        Holding(layout, tmp_path / "missing")


def test_clash_rules_give_up_loudly(env, tmp_path, monkeypatch):
    engine, made, root = env
    layout = vfx(tmp_path, links=MEDIA_VERSION_UP)
    e = engine(layout)
    e.create("media", MEDIA)
    monkeypatch.setattr("entitylayout.engine.CLASH_ATTEMPTS", 1)
    with pytest.raises(ClashError, match="no free key"):
        e.create("media", MEDIA)
