from __future__ import annotations

from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

from entitylayout import Layout, load_config

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_NAMES = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())

settings.register_profile("layout", deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("layout")


@cache
def load_fixture(name: str) -> Layout:
    return load_config(FIXTURES / name)


@pytest.fixture
def make_layout():
    """Build a layout from inline config data."""
    from entitylayout import load_config_data

    def make(keys=None, rules=None, roots=None, version=1):
        return load_config_data(
            {"version": version, "keys": keys or {}, "rules": rules or {}, "roots": roots or {"r": "/base"}}
        )

    return make
