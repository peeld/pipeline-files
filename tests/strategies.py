"""Hypothesis strategies that generate valid fields from a layout's own key definitions."""

from __future__ import annotations

import datetime as dt

from hypothesis import strategies as st

from entitylayout import InvalidValueError, Key, Layout
from entitylayout.keys import DEFAULT_STRING_PATTERN


def _valid(key: Key):
    def check(value) -> bool:
        try:
            key.validate(value)
        except InvalidValueError:
            return False
        return True

    return check


def key_values(key: Key) -> st.SearchStrategy:
    """Every valid value for key, including awkward ones the key's pattern allows."""
    if key.choices is not None:
        return st.sampled_from(key.choices)
    if key.type == "string":
        base = st.from_regex(key.pattern or DEFAULT_STRING_PATTERN, fullmatch=True)
    elif key.type == "int":
        if key.pattern is None:
            base = st.integers(min_value=-(10**12), max_value=10**12)
        else:
            base = st.from_regex(key.pattern, fullmatch=True).filter(lambda t: t.isascii()).map(int)
    else:
        base = st.dates(min_value=dt.date(1, 1, 1))
    return base.filter(_valid(key)).map(key.validate)


@st.composite
def rule_fields(draw, layout: Layout, rule_name: str, backend: str = "fs") -> dict:
    """A full set of fields for one entity of rule_name.

    Keys in optional groups are sometimes left out.
    """
    rule = layout.rule(rule_name)
    optional = rule.template(backend).optional_key_names
    fields = {}
    for name in rule.keys:
        if name in optional and draw(st.booleans()):
            continue
        fields[name] = draw(key_values(layout.keys[name]))
    return fields
