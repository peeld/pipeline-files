"""Location templates: format fields into a location and parse them back.

Template syntax:

- ``{key}`` is replaced by the key's text, as written by ``Key.to_text``.
- ``[ ... ]`` marks an optional group. It is written when its keys are given
  and left out when they are not. Groups cannot nest.
- Everything else is literal text. ``/`` separates path segments.

A key may appear more than once; every occurrence must parse to the same
value. Parsing tries every way of splitting the text, and raises
AmbiguousParseError if more than one split succeeds, so a name that could
mean two different entities is never silently read as one of them.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import AmbiguousParseError, ConfigError, InvalidValueError, MissingKeyError, NoMatchError
from .keys import KEY_NAME, Key

_TOKEN = re.compile(r"\{([^{}]*)\}|\[|\]|[{}]|[^{}\[\]]+")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class KeyRef:
    name: str


@dataclass(frozen=True)
class Optional:
    tokens: tuple[Token, ...]

    @property
    def key_names(self) -> list[str]:
        return [t.name for t in self.tokens if isinstance(t, KeyRef)]


Token = str | KeyRef | Optional


class Template:
    """A compiled template for one rule on one backend."""

    def __init__(self, text: str, keys: Mapping[str, Key], *, context: str = "template") -> None:
        self.text = text
        self.keys = dict(keys)
        self.tokens = _tokenize(text, context)
        self._check(context)

    def __repr__(self) -> str:
        return f"Template({self.text!r})"

    @property
    def key_names(self) -> list[str]:
        """Every key used, in order of first appearance."""
        names: list[str] = []
        for token in _flatten(self.tokens):
            if isinstance(token, KeyRef) and token.name not in names:
                names.append(token.name)
        return names

    @property
    def optional_key_names(self) -> set[str]:
        return {n for t in self.tokens if isinstance(t, Optional) for n in t.key_names}

    def literal_prefix(self) -> str:
        """The fixed text before the first key or optional group."""
        prefix = ""
        for token in self.tokens:
            if not isinstance(token, str):
                break
            prefix += token
        return prefix

    def _check(self, context: str) -> None:
        literal = "".join(t for t in _flatten(self.tokens) if isinstance(t, str))
        if self.text.startswith("/") or _WINDOWS_DRIVE.match(self.text) or "\\" in literal:
            raise ConfigError(f"{context}: {self.text!r} must be relative; absolute locations belong in roots")
        for segment in self.text.split("/"):
            if segment in ("", ".", ".."):
                raise ConfigError(f"{context}: {self.text!r} has an empty, '.' or '..' path segment")
        unknown = [n for n in self.key_names if n not in self.keys]
        if unknown:
            raise ConfigError(f"{context}: {self.text!r} uses undefined keys {unknown}")
        optional = self.optional_key_names
        required = {t.name for t in self.tokens if isinstance(t, KeyRef)}
        both = optional & required
        if both:
            raise ConfigError(f"{context}: keys {sorted(both)} appear both inside and outside an optional group")
        for name in optional:
            if self.keys[name].required:
                raise ConfigError(f"{context}: key {name!r} is in an optional group, so it must set required: false")

    # Fields to location

    def format(self, fields: Mapping[str, Any]) -> str:
        """Build a location from fields.

        Missing keys outside optional groups take their key's default. An
        optional group is written only when its keys are given.
        """
        out = []
        for token in self.tokens:
            if isinstance(token, Optional):
                present = [n for n in token.key_names if fields.get(n) is not None]
                if not present:
                    continue
                if len(present) != len(set(token.key_names)):
                    missing = sorted(set(token.key_names) - set(present))
                    raise MissingKeyError(f"optional group needs all of its keys; missing {missing}")
                out.extend(self._format_tokens(token.tokens, fields))
            else:
                out.extend(self._format_tokens((token,), fields))
        return "".join(out)

    def _format_tokens(self, tokens: tuple[Token, ...], fields: Mapping[str, Any]) -> Iterator[str]:
        for token in tokens:
            if isinstance(token, str):
                yield token
                continue
            key = self.keys[token.name]
            value = fields.get(token.name)
            if value is None:
                value = key.default
            if value is None:
                raise MissingKeyError(f"missing key {token.name!r} for {self.text!r}")
            yield key.to_text(value)

    # Location to fields

    def parse(self, text: str) -> dict[str, Any]:
        """Return the fields encoded in text.

        Raises NoMatchError if text does not fit the template, and
        AmbiguousParseError if it fits in more than one way.
        """
        results: list[dict[str, Any]] = []
        self._match(self.tokens, text, 0, {}, results)
        if not results:
            raise NoMatchError(f"{text!r} does not match {self.text!r}")
        if len(results) > 1:
            readings = "; ".join(repr(r) for r in results)
            raise AmbiguousParseError(f"{text!r} can be read more than one way as {self.text!r}: {readings}")
        return results[0]

    def _match(
        self,
        tokens: tuple[Token, ...],
        text: str,
        pos: int,
        fields: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> None:
        # Two distinct readings are enough to prove ambiguity.
        if len(results) > 1:
            return
        if not tokens:
            if pos == len(text) and fields not in results:
                results.append(dict(fields))
            return
        token, rest = tokens[0], tokens[1:]
        if isinstance(token, str):
            if text.startswith(token, pos):
                self._match(rest, text, pos + len(token), fields, results)
            return
        if isinstance(token, Optional):
            self._match(rest, text, pos, fields, results)
            self._match(token.tokens + rest, text, pos, fields, results)
            return
        key = self.keys[token.name]
        following = rest[0] if rest and isinstance(rest[0], str) else None
        for end in range(pos + 1, len(text) + 1):
            if following is not None and not text.startswith(following, end):
                continue
            try:
                value = key.from_text(text[pos:end])
            except InvalidValueError:
                continue
            if token.name in fields:
                if fields[token.name] == value:
                    self._match(rest, text, end, fields, results)
                continue
            fields[token.name] = value
            self._match(rest, text, end, fields, results)
            del fields[token.name]


def _flatten(tokens: tuple[Token, ...]) -> Iterator[Token]:
    for token in tokens:
        if isinstance(token, Optional):
            yield from token.tokens
        else:
            yield token


def _tokenize(text: str, context: str) -> tuple[Token, ...]:
    if not isinstance(text, str) or not text:
        raise ConfigError(f"{context}: template must be a non-empty string")
    top: list[Token] = []
    group: list[Token] | None = None
    for match in _TOKEN.finditer(text):
        piece = match.group(0)
        target = group if group is not None else top
        if match.group(1) is not None:
            name = match.group(1)
            if not KEY_NAME.fullmatch(name):
                raise ConfigError(f"{context}: {{{name}}} in {text!r} is not a valid key name")
            target.append(KeyRef(name))
        elif piece == "[":
            if group is not None:
                raise ConfigError(f"{context}: optional groups cannot nest in {text!r}")
            group = []
        elif piece == "]":
            if group is None:
                raise ConfigError(f"{context}: unmatched ']' in {text!r}")
            if not any(isinstance(t, KeyRef) for t in group):
                raise ConfigError(f"{context}: optional group in {text!r} contains no key")
            top.append(Optional(_merge_literals(group)))
            group = None
        elif piece in "{}":
            raise ConfigError(f"{context}: unmatched {piece!r} in {text!r}")
        else:
            target.append(piece)
    if group is not None:
        raise ConfigError(f"{context}: unclosed '[' in {text!r}")
    return _merge_literals(top)


def _merge_literals(tokens: list[Token]) -> tuple[Token, ...]:
    merged: list[Token] = []
    for token in tokens:
        if isinstance(token, str) and merged and isinstance(merged[-1], str):
            merged[-1] += token
        else:
            merged.append(token)
    return tuple(merged)
