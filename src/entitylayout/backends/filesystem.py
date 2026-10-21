"""The filesystem backend: entities are files and directories under a root."""

from __future__ import annotations

import dataclasses
import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from ..entity import Entity
from ..errors import ClashError, ConfigError, InvalidValueError, LayoutError, UndoError
from ..keys import Key, nfc
from ..layout import Layout, Rule
from ..location import Location
from ..records import Record, content_hash, sidecar_text
from ..template import KeyRef, Token, format_tokens, match_tokens
from .base import AttributeValidator, Backend, Note

# Values tried to see whether a string key could contain the path separator.
_SEPARATOR_PROBES = ("/", "a/b", "A/B", "1/2", "a/b.c", "a-b/c_d")
# A directory entity's sidecar sits inside it; a file entity's sits beside it. Both are hidden,
# and a leading dot is refused in key values, so a walk never reads a sidecar as an entity.
SIDECAR_NAME = ".entitylayout.json"


class FilesystemBackend(Backend):
    """Finds entities by walking directories one level at a time.

    At each level, a name segment whose keys are all known is checked
    directly; otherwise the directory is listed and each name is parsed
    strictly against the segment, so known keys prune the walk early. The
    full relative path is parsed once more at the end, and a name that reads
    more than one way raises AmbiguousParseError.

    As an active link, it realizes a record as a directory, or as a file when
    the record has a content hash, with a sidecar stamped from the record.
    Each step makes only what is missing and undo removes only what it made.
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

    # Link operations

    def realize(self, record: Record, *, content: bytes | None = None, note: Note) -> None:
        """Make the record's directories, then its sidecar, then its file if it is one (decision 0013)."""
        rule = self._rule(record.rule)
        location = self.layout.locate(record.rule, record.fields, self.name)
        base = self._root_path(rule)
        if not base.is_dir():
            raise LayoutError(f"root {rule.root!r} is not a directory here: {str(base)!r}")
        if content is not None and content_hash(content) != record.content_hash:
            raise LayoutError(f"{location.uri}: the content given does not match record {record.id}'s hash")
        is_file = record.content_hash is not None
        parts = location.path.split("/")

        for depth in range(1, len(parts) + (0 if is_file else 1)):
            relative = "/".join(parts[:depth])
            path = base.joinpath(*parts[:depth])
            if path.is_dir():
                continue
            if os.path.lexists(path):
                raise ClashError(f"{self._uri(rule, relative)}: something that is not a directory is already there")
            note({"make": "dir", "path": relative})
            path.mkdir(exist_ok=True)

        target = base.joinpath(*parts)
        sidecar_relative = _sidecar_path(location.path, is_file)
        sidecar = base / sidecar_relative
        text = sidecar_text(dataclasses.replace(record, location=location))
        if os.path.lexists(sidecar):
            if _read_text(sidecar) != text:
                raise ClashError(f"{location.uri}: a different sidecar is already there, {sidecar.name!r}")
        else:
            note({"make": "sidecar", "path": sidecar_relative})
            _write_new(sidecar, text.encode("utf-8"), record.id, location)

        if not is_file:
            return
        if os.path.lexists(target):
            if not target.is_file() or _file_hash(target) != record.content_hash:
                raise ClashError(f"{location.uri}: a file with different content is already there")
            return
        if content is None:
            raise LayoutError(f"{location.uri}: the file is missing and record {record.id}'s content was not given")
        note({"make": "file", "path": location.path})
        _write_new(target, content, record.id, location)

    def undo(self, record: Record, items: Sequence[Mapping[str, Any]]) -> None:
        rule = self._rule(record.rule)
        base = self._root_path(rule)
        location = self.layout.locate(record.rule, record.fields, self.name)
        sidecar = sidecar_text(dataclasses.replace(record, location=location))
        seen = set()
        for item in reversed(items):
            kind, relative = item["make"], item["path"]
            if (kind, relative) in seen:
                continue
            seen.add((kind, relative))
            path = base.joinpath(*PurePosixPath(relative).parts)
            uri = self._uri(rule, relative)
            if kind in ("sidecar", "file"):
                _temporary(path, record.id).unlink(missing_ok=True)
            if not os.path.lexists(path):
                continue
            if kind == "file":
                if not path.is_file() or _file_hash(path) != record.content_hash:
                    raise UndoError(f"{uri}: the file has changed since record {record.id} wrote it, so it is kept")
                path.unlink()
            elif kind == "sidecar":
                if not path.is_file() or _read_text(path) != sidecar:
                    raise UndoError(f"{uri}: the sidecar has changed since record {record.id} wrote it, so it is kept")
                path.unlink()
            elif kind == "dir":
                if not path.is_dir() or any(path.iterdir()):
                    raise UndoError(f"{uri}: the directory now holds other things, so it is kept")
                path.rmdir()
            else:
                raise LayoutError(f"record {record.id}: the log names an item this backend did not make: {item}")

    def _uri(self, rule: Rule, relative: str) -> str:
        return Location(self.name, rule.root, relative).uri

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


def _sidecar_path(relative: str, is_file: bool) -> str:
    if not is_file:
        return f"{relative}/{SIDECAR_NAME}"
    parent, _, name = relative.rpartition("/")
    return f"{parent}/.{name}{SIDECAR_NAME}" if parent else f".{name}{SIDECAR_NAME}"


def _temporary(path: Path, record_id: str) -> Path:
    # Named by the record, so an undo after a crash can find a half-written file and remove it.
    return path.with_name(f".{path.name}.{record_id}.tmp")


def _write_new(path: Path, data: bytes, record_id: str, location: Location) -> None:
    """Write a file whole, through a temporary file, so no reader ever sees part of it."""
    temporary = _temporary(path, record_id)
    temporary.write_bytes(data)
    if os.path.lexists(path):
        temporary.unlink()
        raise ClashError(f"{location.uri}: {path.name!r} appeared while it was being written")
    os.replace(temporary, path)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


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
