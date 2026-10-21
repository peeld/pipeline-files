from __future__ import annotations

import datetime as dt

import pytest

from entitylayout import ConfigError, InvalidValueError, Key


def test_int_padding_is_canonical():
    shot = Key("shot", "int", pad=3)
    assert shot.to_text(40) == "040"
    assert shot.from_text("040") == 40
    assert shot.to_text(1234) == "1234"
    assert shot.to_text(-7) == "-007"
    for text in ("40", "0040", "+040", "4O"):
        with pytest.raises(InvalidValueError):
            shot.from_text(text)


def test_format_adds_prefix_and_suffix():
    version = Key("version", "int", format="v{value}", pad=3)
    assert version.to_text(3) == "v003"
    assert version.from_text("v003") == 3
    with pytest.raises(InvalidValueError):
        version.from_text("003")
    tagged = Key("tag", format="<{value}>", pattern="[a-z]+")
    assert tagged.from_text("<abc>") == "abc"
    with pytest.raises(InvalidValueError):
        tagged.from_text("<>")


UNSAFE = ["", "a/b", "a\\b", "C:", "..", ".", " lead", "trail ", "trail.", "tab\there", "\ud800", ".hidden"]
WINDOWS_DEVICES = ["CON", "aux", "nul.txt", "COM1", "lpt9.tar.gz"]


@pytest.mark.parametrize("bad", UNSAFE + WINDOWS_DEVICES)
def test_default_string_refuses_unsafe_names(bad):
    with pytest.raises(InvalidValueError):
        Key("name").validate(bad)


def test_explicit_choices_may_use_device_names():
    assert Key("camera", choices=["aux"]).validate("aux") == "aux"


@pytest.mark.parametrize("good", ["Acme & Søn", "a.b", "x", "日本語", "mixed Case 01", "a..b", "CONTOSO", "COM10"])
def test_default_string_allows_ordinary_names(good):
    key = Key("name")
    assert key.from_text(key.to_text(good)) == good


def test_strings_are_stored_in_nfc():
    key = Key("name")
    decomposed = "Café"
    assert key.validate(decomposed) == "Café"
    assert key.from_text(decomposed) == "Café"


def test_explicit_pattern_can_allow_the_separator():
    key = Key("prefix", pattern="[a-z]+(/[a-z]+)*")
    assert key.from_text("a/b/c") == "a/b/c"


def test_choices():
    camera = Key("camera", choices=["main", "witness"])
    assert camera.validate("main") == "main"
    with pytest.raises(InvalidValueError):
        camera.validate("aux")
    quarter = Key("quarter", "int", choices=[1, 2, 3, 4], format="Q{value}")
    assert quarter.from_text("Q2") == 2
    with pytest.raises(InvalidValueError):
        quarter.from_text("Q5")


def test_types_are_strict():
    with pytest.raises(InvalidValueError):
        Key("day", "int").validate("14")
    with pytest.raises(InvalidValueError):
        Key("day", "int").validate(True)
    with pytest.raises(InvalidValueError):
        Key("name").validate(14)
    with pytest.raises(InvalidValueError):
        Key("when", "date").validate(dt.datetime(2026, 1, 1))


def test_coerce_reads_command_line_text():
    assert Key("day", "int").coerce("14") == 14
    assert Key("when", "date").coerce("2026-10-21") == dt.date(2026, 10, 21)
    with pytest.raises(InvalidValueError):
        Key("day", "int").coerce("fourteen")


def test_dates():
    key = Key("when", "date", date_format="%Y%m%d")
    assert key.to_text(dt.date(2026, 3, 9)) == "20260309"
    assert key.from_text("20260309") == dt.date(2026, 3, 9)
    with pytest.raises(InvalidValueError):
        key.from_text("20261309")
    assert Key("when", "date").to_text(dt.date(26, 1, 2)) == "0026-01-02"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "bad-name"},
        {"name": "k", "type": "float"},
        {"name": "k", "format": "no placeholder"},
        {"name": "k", "format": "{value}{value}"},
        {"name": "k", "format": "{value}{x}"},
        {"name": "k", "pad": 3},
        {"name": "k", "type": "int", "pad": -1},
        {"name": "k", "pattern": "("},
        {"name": "k", "type": "date", "pattern": "x"},
        {"name": "k", "type": "date", "date_format": "%Y-%m"},
        {"name": "k", "type": "date", "date_format": "%Y-%m-%d %H"},
        {"name": "k", "choices": []},
        {"name": "k", "type": "int", "choices": ["1"]},
        {"name": "k", "type": "int", "default": "x"},
        {"name": "k", "choices": ["a"], "default": "b"},
    ],
)
def test_bad_key_definitions(kwargs):
    with pytest.raises(ConfigError):
        Key(**kwargs)


def test_unknown_key_property():
    with pytest.raises(ConfigError, match="unknown properties"):
        Key.from_config("k", {"type": "string", "regex": "x"})
