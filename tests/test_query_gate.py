"""Phase 2 gate: a partial-field query returns the expected entities from a real tree.

For every rule of every worked-example fixture, this generates a set of
entities, creates them on disk, then asks for a random subset of keys and
checks the query returns exactly the entities that match.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from entitylayout import FilesystemBackend

from conftest import FIXTURE_NAMES, load_fixture
from strategies import partial_fields, rule_fields
from trees import make_tree

RULES = [(name, rule) for name in FIXTURE_NAMES for rule in load_fixture(name).rules]


@pytest.mark.parametrize(("fixture", "rule"), RULES)
@settings(max_examples=60)
@given(data=st.data())
def test_partial_query_returns_matching_entities(fixture, rule, data):
    layout = load_fixture(fixture)
    entities = data.draw(st.lists(rule_fields(layout, rule), min_size=1, max_size=12))
    query = data.draw(partial_fields(layout, rule, entities))

    with tempfile.TemporaryDirectory() as tmp:
        local = layout.with_roots({layout.rule(rule).root: tmp})
        created = make_tree(local, rule, entities)

        expected = sorted(path for path, fields in created.items() if all(fields.get(k) == v for k, v in query.items()))
        results = FilesystemBackend(local).query(rule, query)

        assert [e.location.path for e in results] == expected
        for entity in results:
            assert entity.fields == created[entity.location.path]
            assert Path(local.real_path(entity.location)).is_dir()
