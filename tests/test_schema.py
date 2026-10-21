"""The JSON Schema accepts every fixture and rejects shapes the loader rejects."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from entitylayout import read_config

from conftest import FIXTURE_NAMES, FIXTURES

SCHEMA = json.loads((Path(__file__).parents[1] / "schema" / "layout.schema.json").read_text())


def test_schema_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixtures_match_schema(name):
    jsonschema.validate(read_config(FIXTURES / name), SCHEMA)


@pytest.mark.parametrize(
    "data",
    [
        {"keys": {}},
        {"version": 1, "extra": {}},
        {"version": 1, "keys": {"k": {"regex": "x"}}},
        {"version": 1, "keys": {"k": {"type": "float"}}},
        {"version": 1, "keys": {"k": {"format": "no placeholder"}}},
        {"version": 1, "keys": {"bad-name": {}}},
        {"version": 1, "rules": {"a": {"templates": {}}}},
        {"version": 1, "rules": {"a": {"templates": {"FS": "x"}}}},
        {"version": 1, "roots": {"r": {"platforms": {"beos": "/x"}}}},
        {"version": 1, "roots": {"r": {}}},
    ],
)
def test_schema_rejects(data):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, SCHEMA)
