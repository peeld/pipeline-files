from __future__ import annotations

import os
import unicodedata

import pytest

from entitylayout import (
    AmbiguousParseError,
    Backend,
    ConfigError,
    EntitySequence,
    FilesystemBackend,
    InvalidValueError,
    LayoutError,
    MissingKeyError,
    OperationNotSupportedError,
    Query,
    collapse_sequence,
    group_by,
    newest,
    sort_by,
    where,
)
from entitylayout.backends import filesystem

from conftest import load_fixture

SHOT = "alpha/shots/ABC/ABC_040/media"
TREE = [
    *(f"{SHOT}/v001/main/ABC_040_v001.{f}.exr" for f in (1001, 1002, 1003)),
    *(f"{SHOT}/v002/main/ABC_040_v002.{f}.exr" for f in (1001, 1002, 1004)),
    f"{SHOT}/v002/main_hero/",
    f"{SHOT}/v001/witness/",
    "alpha/shots/ABC/ABC_050/media/v003/main/",
    "alpha/shots/XYZ/XYZ_010/media/v001/main/",
    "beta/shots/ABC/ABC_040/media/v001/main/",
    # Things the walk must skip.
    "alpha/shots/ABC/notes.txt",
    "alpha/shots/ABC/ABD_040/",
    "alpha/.DS_Store",
    f"{SHOT}/v01/main/",
    f"{SHOT}/v001/main/ABC_040_v001.1001.tif",
    f"{SHOT}/v001/main/thumbs.db",
]


def build(root, paths):
    for path in paths:
        target = root / path
        if path.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("")


@pytest.fixture
def vfx(tmp_path):
    build(tmp_path, TREE)
    layout = load_fixture("vfx").with_roots({"projects": tmp_path})
    return FilesystemBackend(layout)


def paths(entities):
    return [e.location.path for e in entities]


def test_query_by_leading_keys(vfx):
    shots = vfx.query("shot", {"project": "alpha"})
    assert [e.fields for e in shots] == [
        {"project": "alpha", "sequence": "ABC", "shot": 40},
        {"project": "alpha", "sequence": "ABC", "shot": 50},
        {"project": "alpha", "sequence": "XYZ", "shot": 10},
    ]
    assert shots[0].rule == "shot"
    assert shots[0].location == vfx.layout.locate("shot", shots[0].fields)
    assert shots[0].provisional is False


def test_query_by_later_key_scans(vfx):
    # The variant is not in the query, so it matches anything, including no variant.
    assert paths(vfx.query("media", {"shot": 40, "camera": "main"})) == [
        f"{SHOT}/v001/main",
        f"{SHOT}/v002/main",
        f"{SHOT}/v002/main_hero",
        "beta/shots/ABC/ABC_040/media/v001/main",
    ]


def test_query_everything(vfx):
    assert len(vfx.query("media")) == 7
    assert len(vfx.query("frame")) == 6


def test_optional_keys(vfx):
    hero = vfx.query("media", {"variant": "hero"})
    assert [e.fields for e in hero] == [
        {"project": "alpha", "sequence": "ABC", "shot": 40, "version": 2, "camera": "main", "variant": "hero"}
    ]
    without = vfx.query("media", {"project": "alpha", "shot": 40, "version": 2})
    assert paths(without) == [f"{SHOT}/v002/main", f"{SHOT}/v002/main_hero"]


def test_known_keys_prune_the_walk(vfx, monkeypatch):
    listed = []
    real_scandir = os.scandir

    def recording_scandir(path):
        listed.append(os.path.relpath(path, vfx._root_path(vfx.layout.rule("shot"))))
        return real_scandir(path)

    monkeypatch.setattr(filesystem.os, "scandir", recording_scandir)
    result = vfx.query("media", {"project": "alpha", "sequence": "ABC", "shot": 40, "version": 1})
    assert paths(result) == [f"{SHOT}/v001/main", f"{SHOT}/v001/witness"]
    assert listed == [f"{SHOT}/v001"]


def test_newest_per_camera_and_variant(vfx):
    query = Query("media", {"project": "alpha", "shot": 40}).then(newest("version"))
    # Each group stays where it first appeared.
    assert paths(query.run(vfx)) == [f"{SHOT}/v002/main", f"{SHOT}/v001/witness", f"{SHOT}/v002/main_hero"]


def test_newest_within_chosen_keys(vfx):
    latest = newest("version", within=["project", "sequence", "shot"])(vfx.query("media"))
    assert [(e["project"], e["shot"], e["version"]) for e in latest] == [
        ("alpha", 40, 2),
        ("alpha", 50, 3),
        ("alpha", 10, 1),
        ("beta", 40, 1),
    ]


def test_collapse_frames(vfx):
    result = Query("frame", {"project": "alpha", "shot": 40}).then(collapse_sequence("frame")).run(vfx)
    assert len(result) == 2
    first, second = result
    assert isinstance(first, EntitySequence)
    assert first.fields["version"] == 1 and "frame" not in first.fields
    assert first.values == (1001, 1002, 1003)
    assert str(first) == "1001-1003"
    assert second.ranges() == [(1001, 1002), (1004, 1004)]
    assert str(second) == "1001-1002,1004"


def test_sort_group_and_where(vfx):
    media = vfx.query("media")
    ordered = sort_by("camera", "version", reverse=True)(media)
    assert (ordered[0]["camera"], ordered[0]["version"]) == ("witness", 1)
    by_variant = sort_by("variant")(media)
    assert "variant" not in by_variant[0].fields and by_variant[-1]["variant"] == "hero"
    groups = group_by(media, "project", "sequence")
    assert {k: len(v) for k, v in groups.items()} == {("alpha", "ABC"): 5, ("alpha", "XYZ"): 1, ("beta", "ABC"): 1}
    assert len(where(lambda e: e["version"] > 1)(media)) == 3


def test_exists(vfx):
    fields = {"project": "alpha", "sequence": "ABC", "shot": 40, "version": 1, "camera": "witness"}
    assert vfx.exists("media", fields)
    assert not vfx.exists("media", {**fields, "camera": "reference"})
    with pytest.raises(MissingKeyError):
        vfx.exists("media", {"project": "alpha"})


def test_bad_queries(vfx):
    with pytest.raises(LayoutError, match="no keys"):
        vfx.query("shot", {"colour": "red"})
    with pytest.raises(InvalidValueError):
        vfx.query("shot", {"shot": "040"})
    with pytest.raises(OperationNotSupportedError, match="attributes"):
        vfx.query("media", {"shot": 40}, attributes={"status": "approved"})


def test_missing_root(tmp_path):
    backend = FilesystemBackend(load_fixture("vfx").with_roots({"projects": tmp_path / "gone"}))
    with pytest.raises(LayoutError, match="not a directory"):
        backend.query("shot")


def test_operations_are_published():
    assert FilesystemBackend.supported_operations() == {"query", "exists"}
    assert not FilesystemBackend.supports("create")
    assert FilesystemBackend.supports("query")
    assert Backend.supported_operations() == frozenset()
    with pytest.raises(OperationNotSupportedError):
        Backend(load_fixture("vfx"), "fs").query("shot")
    with pytest.raises(NotImplementedError):
        Backend(load_fixture("vfx"), "fs").exists("shot", {})


def test_keys_that_can_contain_the_separator_are_refused(make_layout):
    layout = make_layout(
        {"path": {"pattern": ".+"}}, {"a": {"root": "r", "keys": ["path"], "templates": {"fs": "{path}"}}}
    )
    with pytest.raises(ConfigError, match="can contain '/'"):
        FilesystemBackend(layout)
    # The same rule is fine for a backend whose template it does not have.
    FilesystemBackend(layout, "object")


def test_ambiguous_name_on_disk_raises(make_layout, tmp_path):
    layout = make_layout(
        {"name": {}, "label": {}},
        {"a": {"root": "r", "keys": ["name", "label"], "templates": {"fs": "{name}_{label}"}}},
    )
    build(tmp_path, ["x_y/"])
    backend = FilesystemBackend(layout.with_roots({"r": tmp_path}))
    assert [e.fields for e in backend.query("a")] == [{"name": "x", "label": "y"}]
    # A name that reads two ways is refused even when the query picks one reading.
    build(tmp_path, ["x_y_z/"])
    with pytest.raises(AmbiguousParseError):
        backend.query("a", {"name": "x"})


def test_decomposed_names_on_disk_read_as_nfc(tmp_path):
    decomposed = unicodedata.normalize("NFD", "Café Ltd")
    build(tmp_path, [f"{decomposed}/2026/Q3/{decomposed} 2026 Q3 report.pdf"])
    backend = FilesystemBackend(load_fixture("office").with_roots({"clients": tmp_path}))
    [entity] = backend.query("deliverable", {"year": 2026})
    assert entity["client"] == "Café Ltd"
    assert entity.location == backend.layout.locate("deliverable", entity.fields)
