from __future__ import annotations

from pathlib import Path

import pytest

from entitylayout import (
    AmbiguousParseError,
    ConfigError,
    LayoutError,
    Location,
    Match,
    NoMatchError,
    RootNotMappedError,
    check_roots,
    load_config,
)

from conftest import FIXTURES, load_fixture

KEYS = {"project": {"pattern": "[a-z]+"}, "day": {"type": "int", "format": "day{value}"}, "name": {}}


def test_load_directory_of_files():
    layout = load_fixture("vfx")
    assert layout.version == 1
    assert set(layout.rules) == {"shot", "media", "frame"}


def test_inheritance():
    layout = load_fixture("vfx")
    media = layout.rule("media")
    assert media.keys == ("project", "sequence", "shot", "version", "camera", "variant")
    assert media.root == "projects"
    assert (
        media.template("fs").text == "{project}/shots/{sequence}/{sequence}_{shot}/media/{version}/{camera}[_{variant}]"
    )
    frame = layout.rule("frame")
    assert frame.attributes == {"status": "string", "artist": "string", "task": "string"}


def test_locate_and_parse(make_layout):
    layout = make_layout(
        KEYS, {"media": {"root": "r", "keys": ["project", "day"], "templates": {"fs": "{project}/{day}"}}}
    )
    location = layout.locate("media", {"project": "alpha", "day": 14})
    assert location == Location("fs", "r", "alpha/day14")
    assert location.uri == "fs://r/alpha/day14"
    assert layout.parse("fs://r/alpha/day14") == Match("media", {"project": "alpha", "day": 14})


def test_locate_refuses_unknown_fields_and_backends(make_layout):
    layout = make_layout(KEYS, {"media": {"root": "r", "keys": ["project"], "templates": {"fs": "{project}"}}})
    with pytest.raises(LayoutError, match="no keys"):
        layout.locate("media", {"project": "alpha", "day": 1})
    with pytest.raises(LayoutError, match="no template"):
        layout.locate("media", {"project": "alpha"}, backend="object")
    with pytest.raises(LayoutError, match="no rule"):
        layout.locate("missing", {})


def test_templates_per_backend(make_layout):
    layout = make_layout(
        KEYS,
        {
            "run": {
                "root": "r",
                "keys": ["project", "day"],
                "templates": {"fs": "{project}/{day}", "object": "runs/{project}-{day}"},
            }
        },
    )
    location = layout.locate("run", {"project": "a", "day": 2}, backend="object")
    assert location.uri == "object://r/runs/a-day2"
    assert layout.parse(location) == Match("run", {"project": "a", "day": 2})


def test_location_matching_two_rules_is_ambiguous(make_layout):
    rules = {
        "renders": {"root": "r", "keys": ["project", "name"], "templates": {"fs": "{project}/{name}"}},
        "plates": {"root": "r", "keys": ["project", "day"], "templates": {"fs": "{project}/{day}"}},
    }
    layout = make_layout(KEYS, rules)
    assert [m.rule for m in layout.matches("fs://r/alpha/day1")] == ["renders", "plates"]
    with pytest.raises(AmbiguousParseError, match="several rules"):
        layout.parse("fs://r/alpha/day1")
    assert layout.parse("fs://r/alpha/day1", rule="plates") == Match("plates", {"project": "alpha", "day": 1})
    assert layout.parse("fs://r/alpha/other") == Match("renders", {"project": "alpha", "name": "other"})


def test_parse_with_rule_on_wrong_root(make_layout):
    layout = make_layout(KEYS, {"a": {"root": "r", "keys": ["project"], "templates": {"fs": "{project}"}}})
    with pytest.raises(NoMatchError):
        layout.parse("fs://elsewhere/alpha", rule="a")
    with pytest.raises(NoMatchError):
        layout.parse("fs://elsewhere/alpha")


def test_location_uri_escaping():
    location = Location("fs", "clients", "Acme & Søn/100%/a#b?c")
    assert Location.from_uri(location.uri) == location
    assert " " not in Location("fs", "r", "a b").uri
    with pytest.raises(LayoutError):
        Location.from_uri("/not/a/uri")


ROOTS = {
    "projects": {
        "default": "/mnt/projects",
        "platforms": {"darwin": "/Volumes/projects"},
        "hosts": {"render-*": "/fast/projects"},
    },
    "nested": "/mnt/projects/archive",
    "mac_only": {"platforms": {"darwin": "/Volumes/mac"}},
}


def test_root_resolution(make_layout):
    layout = make_layout(roots=ROOTS)
    projects = layout.roots["projects"]
    assert projects.resolve(platform="linux", host="ws1") == "/mnt/projects"
    assert projects.resolve(platform="darwin", host="ws1") == "/Volumes/projects"
    assert projects.resolve(platform="darwin", host="render-07") == "/fast/projects"
    with pytest.raises(RootNotMappedError):
        layout.roots["mac_only"].resolve(platform="linux", host="ws1")


def test_real_path_and_back(make_layout):
    layout = make_layout(roots=ROOTS)
    location = Location("fs", "projects", "alpha/day14")
    path = layout.real_path(location, platform="linux", host="ws1")
    assert path == Path("/mnt/projects/alpha/day14")
    assert layout.location_for_path(path, platform="linux", host="ws1") == location
    # The deepest root containing a path wins.
    archived = layout.location_for_path("/mnt/projects/archive/alpha", platform="linux", host="ws1")
    assert archived == Location("fs", "nested", "alpha")
    with pytest.raises(NoMatchError):
        layout.location_for_path("/somewhere/else", platform="linux", host="ws1")


def test_check_roots(make_layout, tmp_path):
    (tmp_path / "here").mkdir()
    (tmp_path / "file").write_text("")
    roots = {
        "here": str(tmp_path / "here"),
        "gone": str(tmp_path / "gone"),
        "file": str(tmp_path / "file"),
        "mac_only": {"platforms": {"darwin": "/Volumes/mac"}},
    }
    problems = check_roots(make_layout(roots=roots), platform="linux", host="ws1")
    assert {p.root for p in problems} == {"gone", "file", "mac_only"}
    assert check_roots(make_layout(roots={"here": str(tmp_path / "here")})) == []


def _rules(**rules):
    return rules


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        (_rules(a={"root": "r", "keys": ["nope"], "templates": {"fs": "{nope}"}}), "not defined"),
        (_rules(a={"root": "r", "keys": ["project"], "templates": {"fs": "{project}/{day}"}}), "not rule keys"),
        (_rules(a={"root": "r", "keys": ["project", "day"], "templates": {"fs": "{project}"}}), "missing"),
        (_rules(a={"root": "r", "keys": ["project", "project"], "templates": {"fs": "{project}"}}), "more than once"),
        (_rules(a={"root": "r", "keys": [], "templates": {"fs": "x"}}), "at least one key"),
        (_rules(a={"root": "r", "keys": ["project"]}), "templates"),
        (_rules(a={"keys": ["project"], "templates": {"fs": "{project}"}}), "needs a root"),
        (_rules(a={"root": "x", "keys": ["project"], "templates": {"fs": "{project}"}}), "root 'x'"),
        (_rules(a={"root": "r", "keys": ["project"], "templates": {"FS": "{project}"}}), "backend names"),
        (_rules(a={"root": "r", "keys": ["project"], "templates": {"fs": "{project}"}, "bad": 1}), "unknown"),
        (_rules(a={"parent": "b", "keys": ["project"], "templates": {"fs": "{project}"}}), "not defined"),
        (
            _rules(
                a={"parent": "b", "keys": ["project"], "templates": {"fs": "{project}"}},
                b={"parent": "a", "keys": ["day"], "templates": {"fs": "{day}"}},
            ),
            "cycle",
        ),
        (
            _rules(
                a={"root": "r", "keys": ["project"], "templates": {"fs": "{project}"}},
                b={"parent": "a", "root": "r2", "keys": ["day"], "templates": {"fs": "{day}"}},
            ),
            "differs",
        ),
        (
            _rules(
                a={"root": "r", "keys": ["project"], "templates": {"fs": "{project}", "object": "{project}"}},
                b={"parent": "a", "keys": ["day"], "templates": {"fs": "{day}"}},
            ),
            "does not extend",
        ),
        (
            _rules(
                a={"root": "r", "keys": ["project"], "templates": {"fs": "{project}"}},
                b={"parent": "a", "keys": ["day"], "templates": {"object": "{day}"}},
            ),
            "no 'object' template",
        ),
        (
            _rules(a={"root": "r", "keys": ["project"], "templates": {"fs": "{project}"}, "attributes": {"s": "enum"}}),
            "attribute",
        ),
        (
            _rules(
                a={
                    "root": "r",
                    "keys": ["project"],
                    "templates": {"fs": "{project}"},
                    "attributes": {"project": "string"},
                }
            ),
            "is a key",
        ),
    ],
)
def test_bad_rules(make_layout, rules, message):
    with pytest.raises(ConfigError, match=message):
        make_layout(KEYS, rules, roots={"r": "/base", "r2": "/other"})


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"keys": {}}, "version"),
        ({"version": True}, "version"),
        ({"version": 1, "extra": {}}, "unknown config sections"),
        ({"version": 1, "keys": []}, "must be a mapping"),
        ({"version": 1, "roots": {"bad name": "/x"}}, "root name"),
        ({"version": 1, "roots": {"r": {}}}, "at least one"),
        ({"version": 1, "roots": {"r": {"platforms": {"beos": "/x"}}}}, "unknown platforms"),
        ({"version": 1, "roots": {"r": {"path": "/x"}}}, "unknown properties"),
    ],
)
def test_bad_config(data, message):
    from entitylayout import load_config_data

    with pytest.raises(ConfigError, match=message):
        load_config_data(data)


def test_section_in_two_files(tmp_path):
    (tmp_path / "a.yaml").write_text("version: 1\nkeys: {}\n")
    (tmp_path / "b.yaml").write_text("keys: {}\n")
    with pytest.raises(ConfigError, match="appears in both"):
        load_config(tmp_path)


def test_empty_directory_and_bad_files(tmp_path):
    with pytest.raises(ConfigError, match="no .yaml"):
        load_config(tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text("- a list\n")
    with pytest.raises(ConfigError, match="mapping of sections"):
        load_config(bad)
    bad.write_text("version: [unclosed\n")
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(bad)


def test_json_config(tmp_path):
    (tmp_path / "layout.json").write_text(
        '{"version": "1", "keys": {"k": {}}, "roots": {"r": "/x"},'
        ' "rules": {"a": {"root": "r", "keys": ["k"], "templates": {"fs": "{k}"}}}}'
    )
    assert load_config(tmp_path).locate("a", {"k": "v"}).uri == "fs://r/v"


def test_fixtures_directory_exists():
    assert FIXTURES.is_dir()
