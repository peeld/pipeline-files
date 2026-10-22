"""Authority records, the operation log, content hashes and sidecars (decisions 0013 and 0014)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .entity import Entity
from .errors import LayoutError
from .location import Location

if TYPE_CHECKING:
    from .layout import Layout, Rule

STATES = ("pending", "committed", "out_of_sync", "failed")
# Pending and failed records are seen only by the writing tool and by recovery.
VISIBLE_STATES = ("committed", "out_of_sync")

SIDECAR_FORMAT = "entitylayout.sidecar"
SIDECAR_VERSION = 1
_SIDECAR_FIELDS = (
    "format",
    "format_version",
    "id",
    "rule",
    "location",
    "fields",
    "attributes",
    "config_version",
    "revision",
    "content_hash",
)


@dataclass(frozen=True)
class Record:
    """An entity as its authority holds it: identity, state, revision and content hash."""

    id: str
    rule: str
    fields: dict[str, Any]
    location: Location
    state: str
    revision: int
    config_version: str
    attributes: dict[str, Any] = field(default_factory=dict)
    # A hash of the entity's file, or None when the entity is a directory.
    content_hash: str | None = None
    # Active links that are behind, in order, while the record is out of sync.
    lagging: tuple[str, ...] = ()
    # The fields first asked for, when a clash or a parent's merge gave the record others; else None.
    requested: dict[str, Any] | None = None

    def entity(self) -> Entity:
        return Entity(
            self.rule,
            dict(self.fields),
            self.location,
            attributes=dict(self.attributes),
            id=self.id,
            lagging=self.lagging,
        )


@dataclass(frozen=True)
class Step:
    """One entry in the operation log."""

    seq: int
    operation: str
    record: str
    step: str
    link: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def json_default(value: Any) -> Any:
    """Encode the values keys and attributes hold that JSON lacks: dates as ISO text, tuples as lists."""
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def canonical_json(value: Any) -> str:
    return json.dumps(value, default=json_default, allow_nan=False, ensure_ascii=False, sort_keys=True)


def content_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def decode_fields(layout: Layout, rule: Rule, data: Any, source: str) -> dict[str, Any]:
    """Fields read back from JSON, with dates turned back from ISO text and every value checked."""
    if not isinstance(data, Mapping):
        raise LayoutError(f"{source}: fields must be a JSON object, got {data!r}")
    unknown = sorted(set(data) - set(rule.keys))
    if unknown:
        raise LayoutError(f"{source}: rule {rule.name!r} has no keys {unknown}")
    fields = {}
    for name, value in data.items():
        try:
            if layout.keys[name].type == "date" and isinstance(value, str):
                value = dt.date.fromisoformat(value)
            fields[name] = layout.keys[name].validate(value)
        except ValueError as exc:
            raise LayoutError(f"{source}: key {name!r} holds {value!r}: {exc}") from None
    return fields


def decode_attributes(rule: Rule, stored: str, source: str) -> dict[str, Any]:
    """Attributes read back from JSON text, with declared dates and datetimes turned back from ISO text."""
    try:
        attributes = json.loads(stored)
    except ValueError as exc:
        raise LayoutError(f"{source}: attributes are not valid JSON: {exc}") from None
    if not isinstance(attributes, dict):
        raise LayoutError(f"{source}: attributes must be a JSON object, got {stored!r}")
    for name, value in attributes.items():
        kind = rule.attributes.get(name)
        if kind not in ("date", "datetime") or not isinstance(value, str):
            continue
        try:
            attributes[name] = (dt.date if kind == "date" else dt.datetime).fromisoformat(value)
        except ValueError:
            raise LayoutError(f"{source}: attribute {name!r} is declared {kind} but holds {value!r}") from None
    return attributes


# Sidecars


def sidecar_text(record: Record) -> str:
    """The sidecar for a record: its stamp and a hash of everything above the hash line."""
    body = {
        "format": SIDECAR_FORMAT,
        "format_version": SIDECAR_VERSION,
        "id": record.id,
        "rule": record.rule,
        "location": record.location.uri,
        "fields": record.fields,
        "attributes": record.attributes,
        "config_version": record.config_version,
        "revision": record.revision,
        "content_hash": record.content_hash,
    }
    return (
        json.dumps(
            {**body, "hash": _body_hash(body)}, default=json_default, allow_nan=False, ensure_ascii=False, indent=2
        )
        + "\n"
    )


@dataclass(frozen=True)
class Sidecar:
    """A sidecar read back. ``edited`` is true when its body no longer matches its stamped hash."""

    body: dict[str, Any]
    hash: str

    @property
    def id(self) -> str:
        return self.body["id"]

    @property
    def revision(self) -> int:
        return self.body["revision"]

    @property
    def edited(self) -> bool:
        return _body_hash(self.body) != self.hash

    def stale(self, revision: int) -> bool:
        """Whether the authority has moved past the revision this sidecar was written from."""
        return self.revision < revision


def read_sidecar(text: str, source: str) -> Sidecar:
    """Parse a sidecar, failing with an error that names source if it is not one."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise LayoutError(f"{source}: sidecar is not valid JSON: {exc}") from None
    if not isinstance(data, Mapping) or data.get("format") != SIDECAR_FORMAT:
        raise LayoutError(f"{source}: not an entitylayout sidecar")
    if data.get("format_version") != SIDECAR_VERSION:
        raise LayoutError(f"{source}: sidecar format version {data.get('format_version')!r} is not supported")
    missing = [name for name in (*_SIDECAR_FIELDS, "hash") if name not in data]
    if missing:
        raise LayoutError(f"{source}: sidecar is missing {missing}")
    body = {name: value for name, value in data.items() if name != "hash"}
    return Sidecar(body, data["hash"])


def _body_hash(body: Mapping[str, Any]) -> str:
    return content_hash(canonical_json(body).encode("utf-8"))
