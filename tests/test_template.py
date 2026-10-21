from __future__ import annotations

import pytest
from hypothesis import find
from hypothesis import strategies as st

from entitylayout import AmbiguousParseError, ConfigError, Key, MissingKeyError, NoMatchError, Template

KEYS = {
    "project": Key("project", pattern="[a-z]+"),
    "seq": Key("seq", pattern="[A-Z]+"),
    "shot": Key("shot", "int", pad=3),
    "version": Key("version", "int", format="v{value}", pad=3, default=1),
    "variant": Key("variant", pattern="[a-z]+", required=False),
    "name": Key("name"),
    "label": Key("label"),
    "note": Key("note", required=False),
}


def t(text: str) -> Template:
    return Template(text, KEYS)


@pytest.mark.parametrize(
    "text",
    [
        "{project",
        "project}",
        "{}",
        "{bad-name}",
        "[{variant}",
        "{variant}]",
        "[[{variant}]]",
        "{project}[_x]",
        "/abs/{project}",
        "C:/x/{project}",
        "{project}\\{seq}",
        "{project}/../{seq}",
        "{project}/./{seq}",
        "{project}//{seq}",
        "{project}/",
        "{undefined}",
        "{project}[_{seq}]",
        "{variant}/[{variant}]",
        "",
    ],
)
def test_bad_templates(text):
    with pytest.raises(ConfigError):
        t(text)


def test_format_and_parse():
    tpl = t("{project}/{seq}/{seq}_{shot}/{version}")
    fields = {"project": "alpha", "seq": "AB", "shot": 40, "version": 3}
    assert tpl.format(fields) == "alpha/AB/AB_040/v003"
    assert tpl.parse("alpha/AB/AB_040/v003") == fields
    assert tpl.key_names == ["project", "seq", "shot", "version"]
    assert tpl.literal_prefix() == ""
    assert t("shots/{shot}").literal_prefix() == "shots/"


def test_repeated_key_must_agree():
    tpl = t("{seq}/{seq}_{shot}")
    with pytest.raises(NoMatchError):
        tpl.parse("AB/AC_040")


def test_default_fills_missing_key():
    assert t("{project}/{version}").format({"project": "alpha"}) == "alpha/v001"
    with pytest.raises(MissingKeyError):
        t("{project}/{seq}").format({"project": "alpha"})


def test_optional_group():
    tpl = t("{project}[/{variant}]/{shot}")
    assert tpl.format({"project": "a", "shot": 1}) == "a/001"
    assert tpl.format({"project": "a", "shot": 1, "variant": "hero"}) == "a/hero/001"
    assert tpl.parse("a/001") == {"project": "a", "shot": 1}
    assert tpl.parse("a/hero/001") == {"project": "a", "shot": 1, "variant": "hero"}
    assert tpl.optional_key_names == {"variant"}


def test_optional_group_needs_all_or_none_of_its_keys():
    keys = {**KEYS, "take": Key("take", "int", required=False)}
    tpl = Template("{project}[_{variant}_{take}]", keys)
    assert tpl.format({"project": "a", "variant": "b", "take": 2}) == "a_b_2"
    with pytest.raises(MissingKeyError):
        tpl.format({"project": "a", "variant": "b"})


def test_optional_key_must_not_be_required():
    with pytest.raises(ConfigError, match="required: false"):
        Template("[{project}]", KEYS)


def test_no_match():
    with pytest.raises(NoMatchError):
        t("{project}/{shot}").parse("alpha/40")
    with pytest.raises(NoMatchError):
        t("{project}/{shot}").parse("alpha/040/extra")


def test_ambiguous_split_is_refused():
    # A loosely constrained template is legal; only a name it cannot read one way is refused.
    assert t("{name}_{project}").parse("a_b_c") == {"name": "a_b", "project": "c"}
    tpl = t("{name}_{label}")
    assert tpl.parse("a_b") == {"name": "a", "label": "b"}
    with pytest.raises(AmbiguousParseError, match="more than one way"):
        tpl.parse("a_b_c")


def test_ambiguous_optional_group_is_refused():
    with pytest.raises(AmbiguousParseError):
        t("{name}[_{variant}]").parse("a_b")


def test_round_trip_gate_catches_a_loose_layout():
    """A layout with loosely constrained keys fails the round-trip property, so the gate can fail."""
    tpl = t("{name}_{label}")

    def breaks_round_trip(fields):
        try:
            return tpl.parse(tpl.format(fields)) != fields
        except AmbiguousParseError:
            return True

    example = find(
        st.fixed_dictionaries({"name": st.from_regex("[a-z_]+", fullmatch=True), "label": st.just("x")}),
        breaks_round_trip,
    )
    assert "_" in example["name"]


def test_long_names_parse_quickly():
    tpl = t("{name}/{project}")
    name = "word " * 200 + "end"
    assert tpl.parse(f"{name}/abc") == {"name": name, "project": "abc"}
