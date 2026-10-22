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


INT64 = (-(2**63), 2**63 - 1)

# No unassigned code points: macOS cannot reliably create and then find a file
# name that holds one, although the default string pattern allows them.
NAME_CHARACTERS = st.characters(exclude_categories=("Cs", "Cn"))


def key_values(key: Key, *, int64: bool = False) -> st.SearchStrategy:
    """Every valid value for key, including awkward ones the key's pattern allows.

    With int64, integers stay in the signed 64-bit range SQLite can store.
    """
    if key.choices is not None:
        return st.sampled_from(key.choices)
    if key.type == "string":
        # Capped in length so generated paths stay inside Windows' path limit.
        pattern = key.pattern or DEFAULT_STRING_PATTERN
        base = st.from_regex(pattern, fullmatch=True, alphabet=NAME_CHARACTERS).filter(lambda t: len(t) <= 24)
    elif key.type == "int":
        if key.pattern is None:
            base = st.integers(min_value=-(10**12), max_value=10**12)
        else:
            base = st.from_regex(key.pattern, fullmatch=True).filter(lambda t: t.isascii()).map(int)
        if int64:
            base = base.filter(lambda v: INT64[0] <= v <= INT64[1])
    else:
        base = st.dates(min_value=dt.date(1, 1, 1))
    return base.filter(_valid(key)).map(key.validate)


@st.composite
def rule_fields(draw, layout: Layout, rule_name: str, backend: str = "fs", *, int64: bool = False) -> dict:
    """A full set of fields for one entity of rule_name.

    Keys in optional groups are sometimes left out.
    """
    rule = layout.rule(rule_name)
    optional = rule.template(backend).optional_key_names
    fields = {}
    for name in rule.keys:
        if name in optional and draw(st.booleans()):
            continue
        fields[name] = draw(key_values(layout.keys[name], int64=int64))
    return fields


@st.composite
def partial_fields(draw, layout: Layout, rule_name: str, entities: list[dict], *, int64: bool = False) -> dict:
    """A random subset of rule_name's keys, with values for a query.

    Values come from one of the entities (so results are usually non-empty)
    or are drawn fresh (so they are sometimes empty).
    """
    keys = draw(st.lists(st.sampled_from(layout.rule(rule_name).keys), unique=True))
    source = draw(st.sampled_from(entities))
    query = {}
    for key in keys:
        if key in source and draw(st.booleans()):
            query[key] = source[key]
        else:
            query[key] = draw(key_values(layout.keys[key], int64=int64))
    return query


# Values for each attribute type. Only the scalar ones can be used in an attribute filter.
ATTRIBUTE_VALUES = {
    "string": st.text(max_size=12),
    "int": st.integers(min_value=-(2**53), max_value=2**53),
    "float": st.floats(allow_nan=False, allow_infinity=False),
    "bool": st.booleans(),
    "date": st.dates(),
    "datetime": st.datetimes(),
    "list": st.lists(st.integers(), max_size=3),
    "map": st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
}
SCALAR_ATTRIBUTE_TYPES = ("string", "int", "float", "bool", "date", "datetime")
