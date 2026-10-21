"""Typed keys: the values an entity is identified by."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from .errors import ConfigError, InvalidValueError

KEY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
KEY_TYPES = ("string", "int", "date")
KEY_PROPERTIES = {
    "type",
    "choices",
    "pattern",
    "format",
    "pad",
    "date_format",
    "default",
    "required",
}

# Characters a string key may never contain unless its own pattern allows them:
# the path separator, characters Windows forbids in names, control characters
# and lone surrogates (which cannot be encoded as a file name).
_FORBIDDEN = r'/\\:*?"<>|\x00-\x1f\x7f\ud800-\udfff'
# The default pattern also refuses leading or trailing whitespace and a
# trailing dot, which Windows silently strips from names.
DEFAULT_STRING_PATTERN = rf"[^{_FORBIDDEN}\s](?:[^{_FORBIDDEN}]*[^{_FORBIDDEN}\s.])?"
DEFAULT_INT_PATTERN = r"-?[0-9]+"
_DATE_DIRECTIVES = {"%Y": ("[0-9]{4}", 4), "%m": ("[0-9]{2}", 2), "%d": ("[0-9]{2}", 2)}
_RESERVED_NAMES = {".", ".."}


def nfc(text: str) -> str:
    """Return text in Unicode normal form C, the form keys are stored in."""
    return unicodedata.normalize("NFC", text)


class Key:
    """A typed value that is part of an entity's identity.

    A key converts between a typed value and the text written into a name.
    Both directions are strict: a value is checked against the key's type,
    choices and pattern, and text is accepted only if it is exactly what the
    key would have written for the value it parses to.
    """

    def __init__(
        self,
        name: str,
        type: str = "string",
        *,
        choices: list | tuple | None = None,
        pattern: str | None = None,
        format: str = "{value}",
        pad: int = 0,
        date_format: str = "%Y-%m-%d",
        default: Any = None,
        required: bool = True,
    ) -> None:
        if not KEY_NAME.fullmatch(name):
            raise ConfigError(f"key name {name!r} must start with a letter or '_' and use only letters, digits and '_'")
        if type not in KEY_TYPES:
            raise ConfigError(f"key {name!r}: type must be one of {', '.join(KEY_TYPES)}, not {type!r}")
        self.name = name
        self.type = type
        self.required = bool(required)

        rest = format.replace("{value}", "")
        if format.count("{value}") != 1 or "{" in rest or "}" in rest:
            raise ConfigError(f"key {name!r}: format must contain '{{value}}' exactly once and no other braces")
        self.format = format
        self.prefix, self.suffix = format.split("{value}")

        if pad and type != "int":
            raise ConfigError(f"key {name!r}: pad only applies to int keys")
        if not isinstance(pad, int) or isinstance(pad, bool) or pad < 0:
            raise ConfigError(f"key {name!r}: pad must be a non-negative integer")
        self.pad = pad

        self.date_format = date_format
        if type == "date":
            self._date_regex = _compile_date_format(name, date_format)

        if pattern is not None and type == "date":
            raise ConfigError(f"key {name!r}: date keys take date_format, not pattern")
        self.pattern = pattern
        try:
            self._pattern = re.compile(pattern if pattern is not None else self._default_pattern())
        except re.error as exc:
            raise ConfigError(f"key {name!r}: invalid pattern {pattern!r}: {exc}") from None

        self.choices: tuple | None = None
        if choices is not None:
            if not isinstance(choices, (list, tuple)) or not choices:
                raise ConfigError(f"key {name!r}: choices must be a non-empty list")
            try:
                self.choices = tuple(self.validate(choice, check_choices=False) for choice in choices)
            except InvalidValueError as exc:
                raise ConfigError(f"key {name!r}: bad choice: {exc}") from None

        self.default = None
        if default is not None:
            try:
                self.default = self.validate(default)
            except InvalidValueError as exc:
                raise ConfigError(f"key {name!r}: bad default: {exc}") from None

    @classmethod
    def from_config(cls, name: str, spec: Mapping[str, Any]) -> Key:
        if not isinstance(spec, Mapping):
            raise ConfigError(f"key {name!r}: definition must be a mapping")
        unknown = set(spec) - KEY_PROPERTIES
        if unknown:
            raise ConfigError(f"key {name!r}: unknown properties {sorted(unknown)}")
        return cls(name, **spec)

    def __repr__(self) -> str:
        return f"Key({self.name!r}, {self.type!r})"

    def _default_pattern(self) -> str:
        if self.type == "string":
            return DEFAULT_STRING_PATTERN
        if self.type == "int":
            return DEFAULT_INT_PATTERN
        return self._date_regex.pattern

    # Values

    def validate(self, value: Any, *, check_choices: bool = True) -> Any:
        """Check a value against this key and return it in canonical form.

        Strings are normalized to NFC, so the same name typed on different
        systems compares equal.
        """
        if self.type == "string":
            if not isinstance(value, str):
                raise InvalidValueError(f"{self.name}: expected a string, got {value!r}")
            value = nfc(value)
            if value in _RESERVED_NAMES:
                raise InvalidValueError(f"{self.name}: {value!r} is a reserved name")
            core = value
        elif self.type == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                raise InvalidValueError(f"{self.name}: expected an integer, got {value!r}")
            core = self._int_text(value)
        else:
            if not isinstance(value, dt.date) or isinstance(value, dt.datetime):
                raise InvalidValueError(f"{self.name}: expected a date, got {value!r}")
            core = self._date_text(value)
        if not self._pattern.fullmatch(core):
            raise InvalidValueError(f"{self.name}: {core!r} does not match pattern {self._pattern.pattern!r}")
        if check_choices and self.choices is not None and value not in self.choices:
            raise InvalidValueError(f"{self.name}: {value!r} is not one of {list(self.choices)}")
        return value

    def coerce(self, raw: Any) -> Any:
        """Convert a loosely typed value, such as command-line text, then validate it."""
        if isinstance(raw, str):
            if self.type == "int":
                try:
                    raw = int(raw)
                except ValueError:
                    raise InvalidValueError(f"{self.name}: {raw!r} is not an integer") from None
            elif self.type == "date":
                try:
                    raw = dt.date.fromisoformat(raw)
                except ValueError:
                    raise InvalidValueError(f"{self.name}: {raw!r} is not an ISO date (YYYY-MM-DD)") from None
        return self.validate(raw)

    # Text

    def to_text(self, value: Any) -> str:
        """Return the text this key writes into a name for value."""
        value = self.validate(value)
        if self.type == "int":
            core = self._int_text(value)
        elif self.type == "date":
            core = self._date_text(value)
        else:
            core = value
        return f"{self.prefix}{core}{self.suffix}"

    def from_text(self, text: str) -> Any:
        """Parse text written by to_text back into a value.

        Raises InvalidValueError unless text is exactly the canonical text for
        the value it parses to, so "7" is refused for a key padded to "007".
        """
        text = nfc(text)
        if len(text) < len(self.prefix) + len(self.suffix) or not (
            text.startswith(self.prefix) and text.endswith(self.suffix)
        ):
            raise InvalidValueError(f"{self.name}: {text!r} does not match format {self.format!r}")
        core = text[len(self.prefix) : len(text) - len(self.suffix)]
        if not self._pattern.fullmatch(core):
            raise InvalidValueError(f"{self.name}: {core!r} does not match pattern {self._pattern.pattern!r}")
        if self.type == "int":
            value: Any = int(core)
        elif self.type == "date":
            value = self._parse_date(core)
        else:
            value = core
        if self.to_text(value) != text:
            raise InvalidValueError(f"{self.name}: {text!r} is not in canonical form")
        return value

    def _int_text(self, value: int) -> str:
        sign = "-" if value < 0 else ""
        return f"{sign}{abs(value):0{self.pad}d}"

    def _date_text(self, value: dt.date) -> str:
        return (
            self.date_format.replace("%Y", f"{value.year:04d}")
            .replace("%m", f"{value.month:02d}")
            .replace("%d", f"{value.day:02d}")
        )

    def _parse_date(self, core: str) -> dt.date:
        match = self._date_regex.fullmatch(core)
        if not match:
            raise InvalidValueError(f"{self.name}: {core!r} does not match date format {self.date_format!r}")
        try:
            return dt.date(int(match["Y"]), int(match["m"]), int(match["d"]))
        except ValueError as exc:
            raise InvalidValueError(f"{self.name}: {core!r} is not a valid date: {exc}") from None


def _compile_date_format(name: str, date_format: str) -> re.Pattern:
    parts = re.split(r"(%.)", date_format)
    regex = []
    seen = set()
    for part in parts:
        if part.startswith("%") and len(part) == 2:
            if part not in _DATE_DIRECTIVES:
                raise ConfigError(f"key {name!r}: date_format supports only %Y, %m and %d, not {part}")
            if part in seen:
                raise ConfigError(f"key {name!r}: date_format uses {part} twice")
            seen.add(part)
            regex.append(f"(?P<{part[1]}>{_DATE_DIRECTIVES[part][0]})")
        else:
            regex.append(re.escape(part))
    if seen != set(_DATE_DIRECTIVES):
        raise ConfigError(f"key {name!r}: date_format must use each of %Y, %m and %d once")
    return re.compile("".join(regex))
