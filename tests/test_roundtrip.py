"""Phase 1 gate: every rule round-trips, fields to location and back.

Runs on every rule of every worked-example fixture, with values generated from
each key's own definition, so they include separators, mixed case and
non-ASCII text wherever a key's pattern allows them.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from entitylayout import Location, Match

from conftest import FIXTURE_NAMES, load_fixture
from strategies import rule_fields

RULES = [(name, rule) for name in FIXTURE_NAMES for rule in load_fixture(name).rules]


def test_every_fixture_has_rules():
    assert set(FIXTURE_NAMES) == {"data_science", "industrial_design", "lab", "office", "vfx"}
    assert all(load_fixture(name).rules for name in FIXTURE_NAMES)


@pytest.mark.parametrize(("fixture", "rule"), RULES)
@given(data=st.data())
def test_template_round_trip(fixture, rule, data):
    layout = load_fixture(fixture)
    fields = data.draw(rule_fields(layout, rule))
    template = layout.rule(rule).template("fs")
    assert template.parse(template.format(fields)) == fields


@pytest.mark.parametrize(("fixture", "rule"), RULES)
@given(data=st.data())
def test_location_identifies_rule_and_fields(fixture, rule, data):
    layout = load_fixture(fixture)
    fields = data.draw(rule_fields(layout, rule))
    location = layout.locate(rule, fields)
    assert layout.parse(location) == Match(rule, fields)
    assert Location.from_uri(location.uri) == location
    assert layout.parse(location.uri) == Match(rule, fields)


@pytest.mark.parametrize(("fixture", "rule"), RULES)
@given(data=st.data(), platform=st.sampled_from(["linux", "darwin"]))
def test_real_path_round_trip(fixture, rule, data, platform):
    layout = load_fixture(fixture)
    fields = data.draw(rule_fields(layout, rule))
    location = layout.locate(rule, fields)
    path = layout.real_path(location, platform=platform, host="workstation")
    assert layout.location_for_path(path, platform=platform, host="workstation") == location
