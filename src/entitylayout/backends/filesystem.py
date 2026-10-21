"""The filesystem backend: entities are files and directories under a root."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..entity import Entity
from ..errors import ConfigError, InvalidValueError, LayoutError
from ..keys import Key, nfc
from ..layout import Layout, Rule
from ..location import Location
from ..template import KeyRef, Token, format_tokens, match_tokens
from .base import AttributeValidator, Backend

# Values tried to see whether a string key could contain the path separator.
_SEPARATOR_PROBES = ("/", "a/b", "A/B", "1/2", "a/b.c", "a-b/c_d")


class FilesystemBackend(Backend):
    """Finds entities by walking directories one level at a time.

    At each level, a name segment whose keys are all known is checked
    directly; otherwise the directory is listed and each name is parsed
    strictly against the segment, so known keys prune the walk early. The
    full relative path is parsed once more at the end, and a name that reads
    more than one way raises AmbiguousParseError.
    """

    def __init__(
        self,
        layout: Layout,
        name: str = "fs",
        *,
        platform: str | None = None,
        host: str | None = None,
        validator: AttributeValidator | None = None,
    ) -> None:
        super().__init__(layout, name, validator=validator)
        self.platform = platform
        self.host = host
        for rule in layout.rules.values():
            if name not in rule.templates:
                continue
            for key_name in rule.keys:
                if _can_contain_separator(layout.keys[key_name]):
                    raise ConfigError(
                        f"rule {rule.name!r}: key {key_name!r} can contain '/', "
                        f"which the filesystem would read as a directory"
                    )

    def query(
        self,
        rule: str,
        fields: Mapping[str, Any] | None = None,
        *,
        attributes: Mapping[str, Any] | None = None,
    ) -> list[Entity]:
        self._query_attributes(attributes)
        r = self._rule(rule)
        bound = self._query_fields(r, fields)
        base = self._root_path(r)
        if not base.is_dir():
            raise LayoutError(f"root {r.root!r} is not a directory here: {str(base)!r}")
        template = r.template(self.name)
        found: dict[str, dict[str, Any]] = {}
        listings: dict[Path, list[os.DirEntry]] = {}
        for variant in template.variants():
            # A variant that leaves out an optional key cannot match a query for that key.
            if not ((template.optional_key_names & set(bound)) <= variant.optional_keys):
                continue
            self._walk(base, variant.segments, 0, bound, [], found, listings)
        entities = []
        for relpath, walked in found.items():
            parsed = template.parse(relpath)
            if parsed != walked:
                raise LayoutError(f"internal error: walk read {relpath!r} as {walked}, parse as {parsed}")
            entities.append(Entity(r.name, parsed, Location(self.name, r.root, relpath)))
        entities.sort(key=lambda e: e.location.path)
        return entities

    def exists(self, rule: str, fields: Mapping[str, Any]) -> bool:
        location = self.layout.locate(rule, fields, self.name)
        return os.path.lexists(self.layout.real_path(location, platform=self.platform, host=self.host))

    def _root_path(self, rule: Rule) -> Path:
        return self.layout.real_path(Location(self.name, rule.root, ""), platform=self.platform, host=self.host)

    def _walk(
        self,
        directory: Path,
        segments: tuple[tuple[Token, ...], ...],
        depth: int,
        bound: dict[str, Any],
        parts: list[str],
        found: dict[str, dict[str, Any]],
        listings: dict[Path, list[os.DirEntry]],
    ) -> None:
        if depth == len(segments):
            found.setdefault("/".join(parts), bound)
            return
        segment = segments[depth]
        last = depth == len(segments) - 1
        keys = self.layout.keys
        if all(t.name in bound for t in segment if isinstance(t, KeyRef)):
            try:
                name = format_tokens(segment, keys, bound)
            except InvalidValueError:
                return
            path = directory / name
            if os.path.lexists(path) and (last or path.is_dir()):
                self._walk(path, segments, depth + 1, bound, [*parts, name], found, listings)
            return
        # Each variant of a template may list the same directory, so list it once per query.
        if directory not in listings:
            try:
                with os.scandir(directory) as it:
                    listings[directory] = sorted(it, key=lambda e: e.name)
            except (FileNotFoundError, NotADirectoryError):
                listings[directory] = []
        for entry in listings[directory]:
            if not last and not entry.is_dir():
                continue
            # Names are compared in NFC, the form keys are stored in, whatever the filesystem returns.
            name = nfc(entry.name)
            for reading in match_tokens(segment, name, keys, bound):
                self._walk(Path(entry.path), segments, depth + 1, reading, [*parts, name], found, listings)


def _can_contain_separator(key: Key) -> bool:
    if key.type != "string":
        return False
    for probe in _SEPARATOR_PROBES:
        try:
            key.validate(probe)
        except InvalidValueError:
            continue
        return True
    return key.pattern is not None and "/" in key.pattern
