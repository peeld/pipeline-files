"""Phase 3 gate: the filesystem and SQLite backends answer the same queries identically.

For every rule of every worked-example fixture, this generates a set of
entities once, writes them to a directory tree and into SQLite, runs the same
random partial-field query on both, and requires identical fields and
locations in the same order. Integers stay in the 64-bit range SQLite can
store (decision 0011). A second test checks attribute filters on SQLite
against filtering the stored attributes directly.
"""

from __future__ import annotations

import datetime as dt
import tempfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from entitylayout import FilesystemBackend, Query, SQLiteBackend, newest, sort_by

from conftest import FIXTURE_NAMES, load_fixture
from strategies import ATTRIBUTE_VALUES, SCALAR_ATTRIBUTE_TYPES, partial_fields, rule_fields
from trees import make_tree

RULES = [(name, rule) for name in FIXTURE_NAMES for rule in load_fixture(name).rules]


def _answer(results):
    return [(e.rule, e.fields, e.location) for e in results]


@pytest.mark.parametrize(("fixture", "rule"), RULES)
@settings(max_examples=60)
@given(data=st.data())
def test_both_backends_answer_identically(fixture, rule, data):
    layout = load_fixture(fixture)
    entities = data.draw(st.lists(rule_fields(layout, rule, int64=True), min_size=1, max_size=12))
    query = data.draw(partial_fields(layout, rule, entities, int64=True))

    with tempfile.TemporaryDirectory() as tmp:
        local = layout.with_roots({layout.rule(rule).root: tmp})
        created = make_tree(local, rule, entities)
        with SQLiteBackend(local, ":memory:") as db:
            with db.transaction():
                for fields in created.values():
                    db.create(rule, fields)
            fs = FilesystemBackend(local)

            expected = sorted(
                path for path, fields in created.items() if all(fields.get(k) == v for k, v in query.items())
            )
            on_disk = fs.query(rule, query)
            in_db = db.query(rule, query)
            assert [e.location.path for e in in_db] == expected
            assert _answer(in_db) == _answer(on_disk)

            # Filters run on the results, so the same chain gives the same answer on both.
            key = data.draw(st.sampled_from(layout.rule(rule).keys))
            chain = Query(rule, query).then(newest(key), sort_by(*reversed(layout.rule(rule).keys)))
            assert _answer(chain.run(db)) == _answer(chain.run(fs))

            for path, fields in created.items():
                assert db.exists(rule, fields) and fs.exists(rule, fields), path


@st.composite
def attributes_for(draw, layout, rule_name):
    """Attributes for one entity: some of the rule's declared ones, plus ad-hoc ones of every scalar type."""
    declared = layout.rule(rule_name).attributes
    attributes = {}
    for name, kind in declared.items():
        if draw(st.booleans()):
            attributes[name] = draw(ATTRIBUTE_VALUES[kind])
    for kind in SCALAR_ATTRIBUTE_TYPES:
        if draw(st.booleans()):
            attributes[f"adhoc_{kind}"] = draw(ATTRIBUTE_VALUES[kind])
    return attributes


def _as_stored(layout, rule_name, attributes):
    """Attributes as they read back: dates the rule does not declare come back as ISO text."""
    declared = layout.rule(rule_name).attributes
    return {
        name: value.isoformat() if isinstance(value, dt.date) and name not in declared else value
        for name, value in attributes.items()
    }


def _filterable(layout, rule_name):
    declared = [(n, k) for n, k in layout.rule(rule_name).attributes.items() if k in SCALAR_ATTRIBUTE_TYPES]
    # Declared dates come back as dates; ad-hoc ones come back as ISO text, so they are filtered by that text.
    return declared + [(f"adhoc_{k}", k) for k in SCALAR_ATTRIBUTE_TYPES if k not in ("date", "datetime")]


@pytest.mark.parametrize(("fixture", "rule"), RULES)
@settings(max_examples=40)
@given(data=st.data())
def test_attribute_filters_match_stored_attributes(fixture, rule, data):
    layout = load_fixture(fixture)
    entities = data.draw(
        st.lists(
            st.tuples(rule_fields(layout, rule, int64=True), attributes_for(layout, rule)), min_size=1, max_size=10
        )
    )
    with SQLiteBackend(layout, ":memory:") as db:
        stored = {}
        for fields, attributes in entities:
            location = layout.locate(rule, fields)
            if location.path not in stored:
                db.create(rule, fields, attributes)
                stored[location.path] = (fields, _as_stored(layout, rule, attributes))

        query = data.draw(partial_fields(layout, rule, [f for f, _ in stored.values()], int64=True))
        filters = {}
        source = data.draw(st.sampled_from([a for _, a in stored.values()]))
        for name, kind in data.draw(st.lists(st.sampled_from(_filterable(layout, rule)), unique=True, max_size=2)):
            if name in source and data.draw(st.booleans()):
                filters[name] = source[name]
            else:
                filters[name] = data.draw(ATTRIBUTE_VALUES[kind])

        expected = sorted(
            path
            for path, (fields, attributes) in stored.items()
            if all(fields.get(k) == v for k, v in query.items())
            and all(name in attributes and attributes[name] == v for name, v in filters.items())
        )
        results = db.query(rule, query, attributes=filters)
        assert [e.location.path for e in results] == expected
        for entity in results:
            assert entity.attributes == stored[entity.location.path][1]
