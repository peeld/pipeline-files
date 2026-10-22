"""Holding: new work kept one element at a time while the authority is unreachable (decisions 0002 and 0016).

Each element is a folder named by a fresh uuid, which becomes the entity's
internal ID when it merges.

| File | Holds |
| --- | --- |
| ``manifest.json`` | The ID, rule, requested fields, attributes, held parent, owner, sequence number, time held, hash |
| ``content`` | The file's bytes, for a file entity |
| ``claim.json`` | Who is merging the element now, made by an atomic create |

An element is written in a hidden folder and renamed into place, and a merged
one is renamed to a hidden folder before it is removed, so no reader ever
sees half an element. A name starting with a dot is never an element.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import socket
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .entity import Entity
from .errors import EntityExistsError, HoldingError, InvalidValueError, LayoutError
from .layout import Layout, Rule
from .location import Location
from .records import Record, canonical_json, content_hash, decode_attributes, decode_fields, json_default

HOLDING_FORMAT = "entitylayout.holding"
HOLDING_VERSION = 1
MANIFEST = "manifest.json"
CONTENT = "content"
CLAIM = "claim.json"
_MANIFEST_FIELDS = (
    "format",
    "format_version",
    "id",
    "rule",
    "fields",
    "attributes",
    "parent",
    "owner",
    "sequence",
    "held",
    "config_version",
    "content_hash",
)
# What one merge pass did with an element.
OUTCOMES = (
    # In the authority under the fields asked for, and gone from holding.
    "merged",
    # In the authority under other fields, from a clash rule or a parent's merge, and gone from holding.
    "rekeyed",
    # A clash whose rule is fail, or a parent that is missing or failed. A person decides.
    "needs_decision",
    # The held parent has not merged yet.
    "blocked",
    # The rule merges only when confirmed, or the element is older than max_age.
    "awaiting_confirmation",
    # Another merger holds the element's claim.
    "claimed",
    # The write did not commit, such as a link failure or an unreachable authority. A later merge retries it.
    "incomplete",
)


@dataclass(frozen=True)
class Element:
    """One held entity, as its manifest describes it."""

    id: str
    rule: str
    # The fields asked for, with key defaults filled in.
    fields: dict[str, Any]
    attributes: dict[str, Any]
    # The internal ID of a held parent element, which merges first; None when the parent was not held.
    parent: str | None
    owner: str
    # The order the owner held its elements in. Merging never relies on clocks for order.
    sequence: int
    held: dt.datetime
    config_version: str
    # A hash of the file's content, or None when the entity is a directory.
    content_hash: str | None
    path: Path

    def entity(self, location: Location) -> Entity:
        """The element as a query shows it to its owner: provisional, with its uuid as its ID."""
        return Entity(
            self.rule,
            dict(self.fields),
            location,
            provisional=True,
            attributes=dict(self.attributes),
            id=self.id,
        )


@dataclass(frozen=True)
class MergeResult:
    """What a merge pass did with one element. ``outcome`` is one of OUTCOMES."""

    element: Element
    outcome: str
    # The authority's record, once the merge has reached the authority.
    record: Record | None = None
    reason: str | None = None


class Holding:
    """A directory of held elements, shared or local, written by one owner per element.

    ``owner`` names this machine or user, the host name by default. Queries
    overlay the owner's elements, and a merge takes the owner's elements
    unless asked to adopt others.
    """

    def __init__(self, layout: Layout, path: str | os.PathLike, owner: str | None = None) -> None:
        self.layout = layout
        self.path = Path(path)
        self.owner = owner or socket.gethostname()
        if not self.path.is_dir():
            raise HoldingError(f"holding area {str(self.path)!r} is not a directory")

    def __repr__(self) -> str:
        return f"Holding({str(self.path)!r}, owner={self.owner!r})"

    # Elements

    def hold(
        self,
        rule: str,
        fields: Mapping[str, Any],
        attributes: Mapping[str, Any],
        content: bytes | None,
        *,
        parent: str | None = None,
    ) -> Element:
        """Hold a new entity as an element owned by this holding's owner."""
        r = self.layout.rule(rule)
        fields = full_fields(self.layout, r, fields)
        own = self.elements(owners=[self.owner])
        self._refuse_duplicate(r, fields, own, None)
        element_id = str(uuid.uuid4())
        manifest = {
            "format": HOLDING_FORMAT,
            "format_version": HOLDING_VERSION,
            "id": element_id,
            "rule": r.name,
            "fields": fields,
            "attributes": dict(attributes),
            "parent": parent,
            "owner": self.owner,
            "sequence": 1 + max((e.sequence for e in own), default=0),
            "held": dt.datetime.now(dt.timezone.utc),
            "config_version": str(self.layout.version),
            "content_hash": content_hash(content) if content is not None else None,
        }
        text = _manifest_text(r, manifest)
        staging = self.path / f".{element_id}.tmp"
        staging.mkdir()
        if content is not None:
            (staging / CONTENT).write_bytes(content)
        (staging / MANIFEST).write_text(text, encoding="utf-8")
        os.replace(staging, self.path / element_id)
        return self.element(element_id)

    def elements(self, owners: Iterable[str] | None = None) -> list[Element]:
        """Every held element, or those of the given owners, in owner and sequence order."""
        wanted = None if owners is None else set(owners)
        found = []
        for entry in sorted(self.path.iterdir()):
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            element = self._read(entry)
            if wanted is None or element.owner in wanted:
                found.append(element)
        found.sort(key=lambda e: (e.owner, e.sequence, e.id))
        return found

    def element(self, element_id: str) -> Element:
        path = self.path / element_id
        if not self.has(element_id):
            raise HoldingError(f"{str(self.path)!r} holds no element {element_id}")
        return self._read(path)

    def has(self, element_id: str) -> bool:
        return not element_id.startswith(".") and (self.path / element_id).is_dir()

    def content(self, element: Element) -> bytes | None:
        """The element's file content, checked against its hash; None for a directory."""
        if element.content_hash is None:
            return None
        path = element.path / CONTENT
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise HoldingError(f"held element {element.id}: cannot read its content: {exc}") from None
        if content_hash(data) != element.content_hash:
            raise HoldingError(f"held element {element.id}: its content no longer matches its hash")
        return data

    # Claims

    def claim(self, element: Element, claimant: str) -> bool:
        """Claim an element by an atomic create. True if claimant holds the claim, now or already."""
        record = {"claimant": claimant, "since": dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            with open(element.path / CLAIM, "x", encoding="utf-8") as handle:
                handle.write(json.dumps(record))
        except FileExistsError:
            return self.claimant(element) == claimant
        return True

    def claimant(self, element: Element) -> str | None:
        """Who holds the element's claim, or None. An unreadable claim is held by an unknown claimant, ''."""
        try:
            text = (element.path / CLAIM).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            return str(json.loads(text)["claimant"])
        except (ValueError, KeyError, TypeError):
            return ""

    def release(self, element: Element, claimant: str | None) -> None:
        """Drop claimant's claim. With None, drop whoever holds it, as a person may after a merger dies."""
        if claimant is None or self.claimant(element) == claimant:
            (element.path / CLAIM).unlink(missing_ok=True)

    # After a merge, or a person's decision

    def remove(self, element: Element) -> None:
        """Remove a merged element: hide it first, so a crash part way leaves no half element."""
        hidden = self.path / f".{element.id}.merged"
        os.replace(element.path, hidden)
        shutil.rmtree(hidden)

    def sweep(self) -> None:
        """Finish removing merged elements that a crash left hidden."""
        for entry in self.path.glob(".*.merged"):
            shutil.rmtree(entry)

    def retarget(self, element_id: str, fields: Mapping[str, Any]) -> Element:
        """A person's decision: ask for other fields. Held children follow by ID."""
        element = self.element(element_id)
        rule = self.layout.rule(element.rule)
        fields = full_fields(self.layout, rule, fields)
        self._refuse_duplicate(rule, fields, self.elements(owners=[element.owner]), element.id)
        manifest = json.loads((element.path / MANIFEST).read_text(encoding="utf-8"))
        manifest["fields"] = fields
        temporary = element.path / f".{MANIFEST}.tmp"
        temporary.write_text(_manifest_text(rule, manifest), encoding="utf-8")
        os.replace(temporary, element.path / MANIFEST)
        return self.element(element_id)

    def discard(self, element_id: str) -> None:
        """A person's decision: delete an element and its content. Nothing else ever deletes unmerged work."""
        element = self.element(element_id)
        children = [e.id for e in self.elements() if e.parent == element.id]
        if children:
            raise HoldingError(f"held element {element.id} is the parent of {children}, so decide those first")
        self.remove(element)

    # Helpers

    def _refuse_duplicate(self, rule: Rule, fields: dict[str, Any], own: list[Element], other_than: str | None) -> None:
        for element in own:
            if element.rule == rule.name and element.fields == fields and element.id != other_than:
                raise EntityExistsError(f"rule {rule.name!r}: held element {element.id} already asks for {fields}")

    def _read(self, path: Path) -> Element:
        source = str(path / MANIFEST)
        try:
            data = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HoldingError(f"{source}: cannot read the manifest: {exc}") from None
        if not isinstance(data, Mapping) or data.get("format") != HOLDING_FORMAT:
            raise HoldingError(f"{source}: not an entitylayout holding manifest")
        if data.get("format_version") != HOLDING_VERSION:
            raise HoldingError(f"{source}: manifest format version {data.get('format_version')!r} is not supported")
        missing = [name for name in _MANIFEST_FIELDS if name not in data]
        if missing:
            raise HoldingError(f"{source}: manifest is missing {missing}")
        if data["id"] != path.name:
            raise HoldingError(f"{source}: manifest names element {data['id']}, but its folder is {path.name!r}")
        try:
            rule = self.layout.rule(data["rule"])
            held = dt.datetime.fromisoformat(data["held"])
        except (LayoutError, TypeError, ValueError) as exc:
            raise HoldingError(f"{source}: {exc}") from None
        return Element(
            id=data["id"],
            rule=rule.name,
            fields=decode_fields(self.layout, rule, data["fields"], source),
            attributes=decode_attributes(rule, canonical_json(data["attributes"]), source),
            parent=data["parent"],
            owner=data["owner"],
            sequence=data["sequence"],
            held=held,
            config_version=data["config_version"],
            content_hash=data["content_hash"],
            path=path,
        )


def full_fields(layout: Layout, rule: Rule, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Fields checked and with key defaults filled in, by formatting them and reading them back."""
    backend = next(iter(rule.templates))
    return rule.templates[backend].parse(layout.locate(rule.name, fields, backend).path)


def _manifest_text(rule: Rule, manifest: Mapping[str, Any]) -> str:
    try:
        return json.dumps(manifest, default=json_default, allow_nan=False, ensure_ascii=False, indent=2) + "\n"
    except (TypeError, ValueError) as exc:
        raise InvalidValueError(f"rule {rule.name!r}: the attributes cannot be held: {exc}") from None
