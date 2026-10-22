"""Reading the links section: one authority per rule, ordered active links, and inheritance."""

from __future__ import annotations

import datetime as dt

import pytest

from entitylayout import ConfigError, load_config_data

from conftest import FIXTURE_NAMES, load_fixture

KEYS = {"a": {}, "b": {}}
RULES = {
    "parent": {"root": "r", "keys": ["a"], "templates": {"fs": "{a}"}},
    "child": {"parent": "parent", "keys": ["b"], "templates": {"fs": "{b}"}},
    "other": {"root": "r", "keys": ["b"], "templates": {"fs": "other/{b}"}},
}
BASIC = {"db": {"role": "authority"}, "files": {"role": "active"}}


def layout(links):
    return load_config_data({"version": 1, "keys": KEYS, "rules": RULES, "roots": {"r": "/base"}, "links": links})


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_fixture_gives_every_rule_an_authority_and_an_active_link(name):
    for rule in load_fixture(name).rules.values():
        assert rule.links is not None
        assert rule.links.authority.role == "authority"
        assert len(rule.links.active) == 1 and rule.links.active[0].role == "active"


def test_merge_trigger_and_age_limit_come_with_hold():
    held = {**BASIC, "db": {"role": "authority", "offline": "hold", "merge": "confirm", "max_age": "36h"}}
    authority = layout({"parent": held}).rule("parent").links.authority
    assert (authority.merge, authority.max_age) == ("confirm", dt.timedelta(hours=36))
    plain = layout({"parent": BASIC}).rule("parent").links.authority
    assert (plain.merge, plain.max_age) == ("auto", None)
    with pytest.raises(ConfigError, match=r"\['max_age'\] only apply when offline is hold"):
        layout({"parent": {**BASIC, "db": {"role": "authority", "max_age": "7d"}}})
    with pytest.raises(ConfigError, match="merge must be one of"):
        layout({"parent": {**held, "db": {**held["db"], "merge": "later"}}})
    for bad in ("7", "7 days", "0d", 7):
        with pytest.raises(ConfigError, match="max_age must be"):
            layout({"parent": {**held, "db": {**held["db"], "max_age": bad}}})
    with pytest.raises(ConfigError, match="cannot be set on an active link"):
        layout({"parent": {**BASIC, "files": {"role": "active", "merge": "auto"}}})


def test_defaults_and_roles():
    links = layout({"parent": {**BASIC, "archive": {"role": "passive", "triggers": ["approved"]}}}).rule("parent").links
    assert (links.authority.name, links.authority.offline, links.authority.clash) == ("db", "fail", "fail")
    (files,) = links.active
    assert (files.rollback, files.order, files.clash, files.offline) == (True, None, "fail", None)
    (archive,) = links.passive
    assert (archive.triggers, archive.rollback) == (("approved",), False)
    assert [link.name for link in links] == ["db", "files", "archive"]


def test_a_child_inherits_its_parents_links_unless_it_has_its_own():
    own = {"db": {"role": "authority", "offline": "read_only"}, "share": {"role": "active", "rollback": False}}
    loaded = layout({"parent": BASIC, "child": own})
    assert loaded.rule("child").links.declared_by == "child"
    assert loaded.rule("child").links.active[0].name == "share"
    assert layout({"parent": BASIC}).rule("child").links.declared_by == "parent"
    assert layout({"parent": BASIC}).rule("other").links is None


def test_active_links_follow_their_order():
    links = (
        layout(
            {
                "parent": {
                    "db": {"role": "authority"},
                    "b": {"role": "active", "order": 2},
                    "a": {"role": "active", "order": 1},
                }
            }
        )
        .rule("parent")
        .links
    )
    assert [link.name for link in links.active] == ["a", "b"]


@pytest.mark.parametrize(
    ("links", "message"),
    [
        ({"nope": BASIC}, "rule 'nope', which is not defined"),
        ({"parent": {}}, "non-empty mapping"),
        ({"parent": {"files": {"role": "active"}}}, "exactly one authority, found none"),
        ({"parent": {**BASIC, "db2": {"role": "authority"}}}, r"exactly one authority, found \['db', 'db2'\]"),
        ({"parent": {"db": {"role": "boss"}}}, "role must be one of"),
        ({"parent": {"db": "authority"}}, "settings must be a mapping"),
        ({"parent": {"bad name": {"role": "authority"}}}, "link names may contain only"),
        ({"parent": {"db": {"role": "authority", "order": 1}}}, r"\['order'\] cannot be set on an authority link"),
        ({"parent": {**BASIC, "x": {"role": "passive", "rollback": True}}}, "cannot be set on a passive link"),
        ({"parent": {"db": {"role": "authority"}, "f": {"role": "active", "triggers": ["x"]}}}, "cannot be set"),
        ({"parent": {"db": {"role": "authority", "offline": "panic"}}}, "offline must be one of"),
        ({"parent": {"db": {"role": "authority", "clash": "overwrite"}}}, "clash must be one of"),
        ({"parent": {**BASIC, "f2": {"role": "active"}}}, r"active links \['files', 'f2'\] need an order"),
        (
            {
                "parent": {
                    "db": {"role": "authority"},
                    "a": {"role": "active", "order": 1},
                    "b": {"role": "active", "order": 1},
                }
            },
            r"share order \[1\]",
        ),
        ({"parent": {"db": {"role": "authority"}, "f": {"role": "active", "order": "1"}}}, "order must be an integer"),
        ({"parent": {"db": {"role": "authority"}, "f": {"role": "active", "rollback": "no"}}}, "rollback must be"),
        ({"parent": {**BASIC, "x": {"role": "passive", "triggers": "approved"}}}, "list of event names"),
        ({"parent": {**BASIC, "x": {"role": "passive", "triggers": ["a", "a"]}}}, "more than once"),
    ],
)
def test_bad_links(links, message):
    with pytest.raises(ConfigError, match=message):
        layout(links)
