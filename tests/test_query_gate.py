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
from entitylayout.keys import nfc

from conftest import FIXTURE_NAMES, load_fixture
from strategies import key_values, rule_fields

RULES = [(name, rule) for name in FIXTURE_NAMES for rule in load_fixture(name).rules]


@pytest.mark.parametrize(("fixture", "rule"), RULES)
@settings(max_examples=60)
@given(data=st.data())
def test_partial_query_returns_matching_entities(fixture, rule, data):
    layout = load_fixture(fixture)
    entities = data.draw(st.lists(rule_fields(layout, rule), min_size=1, max_size=12))

    # Pick query keys, taking values from a stored entity (so results are
    # usually non-empty) or drawing fresh ones (so they are sometimes empty).
    keys = data.draw(st.lists(st.sampled_from(layout.rule(rule).keys), unique=True))
    source = data.draw(st.sampled_from(entities))
    query = {}
    for key in keys:
        if key in source and data.draw(st.booleans()):
            query[key] = source[key]
        else:
            query[key] = data.draw(key_values(layout.keys[key]))

    with tempfile.TemporaryDirectory() as tmp:
        local = layout.with_roots({layout.rule(rule).root: tmp})
        created = {}
        spelled: dict[str, str] = {}
        for fields in entities:
            location = local.locate(rule, fields)
            # Skip paths with any level that differs from an earlier one only by
            # case, because the two would share a directory on Windows and macOS.
            parts = location.path.split("/")
            prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
            if any(spelled.get(nfc(p).casefold(), p) != p for p in prefixes):
                continue
            spelled.update((nfc(p).casefold(), p) for p in prefixes)
            local.real_path(location).mkdir(parents=True, exist_ok=True)
            created[location.path] = fields

        expected = sorted(path for path, fields in created.items() if all(fields.get(k) == v for k, v in query.items()))
        results = FilesystemBackend(local).query(rule, query)

        assert [e.location.path for e in results] == expected
        for entity in results:
            assert entity.fields == created[entity.location.path]
            assert Path(local.real_path(entity.location)).is_dir()
