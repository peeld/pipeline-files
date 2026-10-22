"""The write flow: reserve in the authority, realize the active links in order, then settle (decision 0013).

Every write ends in one of the record states the write lifecycle declares.
Committed means the authority and every active link agree. Out of sync means
the record is kept and some links are behind. Failed means the write was
undone. Pending means the write stopped part way, and ``recover`` finishes or
undoes it from the operation log.

When the authority is unreachable and its offline policy is hold, a create
goes to holding instead, and ``merge`` later writes it through the same flow
under its holding uuid (decisions 0015 and 0016). A key that is taken is
settled by the clash rule of the link that found it (decision 0017).

Passive links run only when a tool calls ``realize_passive``, by link name
or by event name, on a committed record (decision 0019). They use the same
link steps, outside any commit, and never roll back or retry.

The flow is a list of named steps, and the engine calls ``checkpoint`` with
each name just before the step runs. Raising an exception there is how tests
make a step fail.

| Step | When |
| --- | --- |
| ``probe:<link>`` | Before an active link whose clash rule is not fail is checked for a clash |
| ``reserve`` | Before the authority records the entity as pending, once per key tried |
| ``passive:<link>`` | Before a passive link's run is logged, ahead of its ``realize:<link>`` |
| ``realize:<link>`` | Before an active or passive link starts |
| ``<link>:<item>`` | Before a link makes one item, such as ``files:dir``, once the item is in the log |
| ``realized:<link>`` | After a link has made everything |
| ``undo:<link>`` | Before a link's items are removed during a rollback |
| ``settle:<state>`` | Before the authority moves the record to committed, out_of_sync or failed |
| ``hold`` | Before a held element is written |
| ``claim`` | Before a merge claims an element, or a merge or recovery claims a record |
| ``clear`` | Before a merged element is removed from holding |
"""

from __future__ import annotations

import datetime as dt
import os
import socket
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .backends.base import AUTHORITY_OPERATIONS, LINK_OPERATIONS, Backend
from .entity import Entity
from .errors import (
    ClashError,
    ConfigError,
    EntityExistsError,
    LayoutError,
    NoRecordError,
    OperationNotSupportedError,
    OutOfSyncError,
    ReadOnlyError,
    UnreachableError,
    WriteError,
    WriteIncompleteError,
    WriteRolledBackError,
)
from .holding import Element, Holding, MergeResult, full_fields
from .layout import Layout, Rule
from .links import Link, Links
from .records import Record, Step, content_hash

Checkpoint = Callable[[str], None]
# How many keys a clash rule tries before it gives up.
CLASH_ATTEMPTS = 100


class _Stop(Exception):
    """Ends one element's merge with an outcome other than merged."""

    def __init__(self, outcome: str, reason: str) -> None:
        super().__init__(reason)
        self.outcome = outcome


def _no_checkpoint(step: str) -> None:
    pass


@dataclass(frozen=True)
class PassiveResult:
    """What one passive link did with a record. ``error`` is None when the link was realized."""

    link: str
    error: Exception | None = None

    @property
    def realized(self) -> bool:
        return self.error is None


class Engine:
    """Writes entities through their authority and active links, and reads them from the authority.

    ``stores`` binds each link name in the layout's links section to a
    backend. Every authority and active link must be bound. A passive link
    may be left out; it is needed only when ``realize_passive`` runs it.

    ``holding`` is where creates go when an authority with the offline policy
    hold is unreachable, and the only place ``merge`` takes elements from.
    ``claimant`` names this engine in claims. It is unique to the engine
    unless given; a machine that names itself the same way after a crash
    takes back the claims it left.
    """

    def __init__(
        self,
        layout: Layout,
        stores: Mapping[str, Backend],
        *,
        holding: Holding | None = None,
        checkpoint: Checkpoint | None = None,
        claimant: str | None = None,
    ) -> None:
        self.layout = layout
        self.stores = dict(stores)
        self.holding = holding
        self.checkpoint = checkpoint or _no_checkpoint
        self.claimant = claimant or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"
        for rule in layout.rules.values():
            if rule.links is not None:
                self._check(rule, rule.links)

    def __repr__(self) -> str:
        return f"Engine({sorted(self.stores)})"

    # Writes

    def create(
        self,
        rule: str,
        fields: Mapping[str, Any],
        attributes: Mapping[str, Any] | None = None,
        *,
        content: bytes | None = None,
    ) -> Entity:
        """Create an entity in the authority and every active link, or raise a WriteError saying how it ended.

        With content, the entity is a file holding it; without, a directory.
        If the authority is unreachable and its offline policy is hold, the
        entity is held instead, and comes back provisional.
        """
        r = self.layout.rule(rule)
        links = self._links(r)
        operation = str(uuid.uuid4())
        try:
            record = self._reserve(r, links, operation, fields, attributes, content, record_id=str(uuid.uuid4()))
        except UnreachableError as exc:
            if links.authority.offline == "hold":
                return self._hold(r, links, fields, attributes, content)
            if links.authority.offline == "read_only":
                raise ReadOnlyError(
                    f"rule {rule!r}: the authority {links.authority.name!r} is unreachable "
                    f"and its offline policy is read_only, so nothing was written"
                ) from exc
            raise
        return self._forward(r, links, record, operation, content).entity()

    def retry(self, rule: str, record: str, *, content: bytes | None = None) -> Entity:
        """Catch up the lagging links of an out of sync record, with the file's content if it is needed."""
        r = self.layout.rule(rule)
        links = self._links(r)
        found = self.stores[links.authority.name].record(record)
        if found.state != "out_of_sync":
            raise LayoutError(f"record {record} ({found.location.uri}) is {found.state}, not out of sync")
        return self._recover(found, content).entity()

    def recover(self) -> list[Record]:
        """Finish every write the operation log shows as unsettled, and return the records as they end.

        A pending write that was rolling back is undone. Any other pending
        write is realized again, which is safe because link steps are
        idempotent, and then committed. An out of sync record has its lagging
        links retried, and stays out of sync if one fails again.

        Each record is claimed first, so two recoveries never work on one
        record. A record another claimant holds is skipped and left as it is.
        """
        results = []
        authorities = {id(self.stores[r.links.authority.name]): r.links.authority.name for r in self._linked_rules()}
        for name in authorities.values():
            authority = self.stores[name]
            for record in authority.unsettled():
                self.checkpoint("claim")
                if not authority.claim(record.id, self.claimant):
                    continue
                try:
                    current = authority.record(record.id)
                    # Another recovery may have settled it before this claim.
                    if current.state in ("pending", "out_of_sync"):
                        results.append(self._recover(current))
                except WriteError as exc:
                    results.append(exc.record)
                except Exception:
                    authority.release(record.id, self.claimant)
                    raise
                authority.release(record.id, self.claimant)
        return results

    def release(self, rule: str, record: str) -> None:
        """Drop whatever claim holds a record, as a person may after a recovery or merge dies part way."""
        self.stores[self._links(self.layout.rule(rule)).authority.name].release(record, None)

    def realize_passive(
        self,
        rule: str,
        record: str,
        *,
        link: str | None = None,
        event: str | None = None,
        content: bytes | None = None,
    ) -> list[PassiveResult]:
        """Realize a committed record in one passive link, or in every one that event triggers, in config order.

        Each link runs the same steps as an active link, logged in the
        authority, but outside the commit: the record stays as it is whatever
        happens. A link that fails is reported in its result and the next one
        still runs. Nothing is rolled back or retried; calling again is safe,
        because link steps are idempotent. A file entity needs its content
        unless the link already holds it.

        An event no rule's passive link names is refused, as a likely typo. An
        event this rule's links do not name runs nothing.
        """
        r = self.layout.rule(rule)
        links = self._links(r)
        if (link is None) == (event is None):
            raise LayoutError(f"rule {rule!r}: give exactly one of link= or event= to realize passive links")
        if link is not None:
            chosen = [p for p in links.passive if p.name == link]
            if not chosen:
                names = [p.name for p in links.passive]
                raise ConfigError(f"rule {rule!r} has no passive link {link!r}; its passive links are {names}")
        else:
            named = {t for rl in self._linked_rules() for p in rl.links.passive for t in p.triggers}
            if event not in named:
                raise ConfigError(f"no rule has a passive link triggered by {event!r}; the events are {sorted(named)}")
            chosen = [p for p in links.passive if event in p.triggers]
        unbound = [p.name for p in chosen if p.name not in self.stores]
        if unbound:
            raise ConfigError(f"rule {rule!r}: passive links {unbound} are not bound to a backend")
        authority = self.stores[links.authority.name]
        found = authority.record(record)
        if found.rule != r.name:
            raise LayoutError(f"record {record} ({found.location.uri}) is of rule {found.rule!r}, not {rule!r}")
        if found.state != "committed":
            raise LayoutError(f"record {record} ({found.location.uri}) is {found.state}, so its passive links wait")
        detail = {"event": event} if event else None
        results = []
        for passive in chosen:
            operation = str(uuid.uuid4())
            try:
                self.checkpoint(f"passive:{passive.name}")
                authority.log(operation, found.id, "passive", link=passive.name, detail=detail)
                self._realize(passive, authority, found, operation, content)
            except Exception as exc:
                results.append(PassiveResult(passive.name, exc))
            else:
                results.append(PassiveResult(passive.name))
        return results

    # Holding and merge

    def merge(
        self,
        *,
        confirm: Iterable[str] = (),
        adopt: Iterable[str] = (),
        now: dt.datetime | None = None,
    ) -> list[MergeResult]:
        """Merge held elements into their authorities, parents first, and say what became of each.

        It takes this holding owner's elements, and those of the owners in
        adopt, such as a machine that failed. An element whose rule merges on
        confirm, or that has waited longer than its max_age, waits unless its
        ID is in confirm. Merging is by internal ID, so running it again, or
        on a copy of an element, never makes a second record.
        """
        holding = self._holding()
        now = now or dt.datetime.now(dt.timezone.utc)
        confirmed = set(confirm)
        holding.sweep()
        elements = holding.elements(owners=[holding.owner, *adopt])
        return [self._merge(holding, e, e.id in confirmed, now) for e in _parents_first(elements)]

    # Reads

    def query(
        self,
        rule: str,
        fields: Mapping[str, Any] | None = None,
        *,
        attributes: Mapping[str, Any] | None = None,
    ) -> list[Entity]:
        """Query the authority, with this holding owner's elements overlaid and flagged provisional.

        If the authority is unreachable and the offline policy is read_only
        or hold, an active link is queried instead.
        """
        r = self.layout.rule(rule)
        links = self._links(r)
        authority = self.stores[links.authority.name]
        try:
            found = authority.query(rule, fields, attributes=attributes)
        except UnreachableError:
            if links.authority.offline not in ("read_only", "hold"):
                raise
            for link in links.active:
                backend = self.stores[link.name]
                if backend.supports("query"):
                    found = backend.query(rule, fields, attributes=attributes)
                    break
            else:
                raise
        if self.holding is None:
            return found
        held = self._overlay(r, authority, fields, attributes)
        return sorted([*found, *held], key=lambda e: e.location.path)

    def record(self, rule: str, record: str) -> Record:
        """A record from rule's authority, in any state."""
        return self.stores[self._links(self.layout.rule(rule)).authority.name].record(record)

    # The flow

    def _reserve(
        self,
        rule: Rule,
        links: Links,
        operation: str,
        fields: Mapping[str, Any],
        attributes: Mapping[str, Any] | None,
        content: bytes | None,
        *,
        record_id: str,
        requested: Mapping[str, Any] | None = None,
    ) -> Record:
        """Reserve under fields, or under the key the clash rule of the link that found a clash gives.

        Active links with a clash rule other than fail are checked first, then
        the authority refuses a key it holds. Only an unreachable authority
        raises UnreachableError, so a caller can hold the work instead.
        """
        authority = self.stores[links.authority.name]
        digest = content_hash(content) if content is not None else None
        candidate = dict(fields)
        for _ in range(CLASH_ATTEMPTS):
            found = self._probe(rule, links, candidate, attributes, digest, record_id)
            if found is None:
                try:
                    self.checkpoint("reserve")
                    return authority.reserve(
                        rule.name,
                        candidate,
                        attributes,
                        operation=operation,
                        content_hash=digest,
                        record_id=record_id,
                        requested=fields if requested is None else requested,
                    )
                except EntityExistsError:
                    if links.authority.clash == "fail":
                        raise
                    found = links.authority
            candidate = self._next_key(rule, found.clash, candidate, authority)
        raise ClashError(f"rule {rule.name!r}: no free key in {CLASH_ATTEMPTS} tries, starting from {dict(fields)}")

    def _probe(
        self,
        rule: Rule,
        links: Links,
        fields: Mapping[str, Any],
        attributes: Mapping[str, Any] | None,
        digest: str | None,
        record_id: str,
    ) -> Link | None:
        """The first active link, of those whose clash rule is not fail, where the key is taken by something else."""
        probing = [link for link in links.active if link.clash != "fail"]
        if not probing:
            return None
        full = full_fields(self.layout, rule, fields)
        record = Record(
            id=record_id,
            rule=rule.name,
            fields=full,
            location=self.layout.locate(rule.name, full, self.stores[links.authority.name].name),
            state="pending",
            revision=1,
            config_version=str(self.layout.version),
            attributes=dict(attributes or {}),
            content_hash=digest,
        )
        for link in probing:
            self.checkpoint(f"probe:{link.name}")
            try:
                taken = self.stores[link.name].clash(record)
            except LayoutError as exc:
                raise WriteError(
                    f"rule {rule.name!r}: link {link.name!r} could not be checked for a clash, "
                    f"so nothing was written: {exc}"
                ) from exc
            if taken is not None:
                return link
        return None

    def _next_key(self, rule: Rule, how: str, fields: Mapping[str, Any], authority: Backend) -> dict[str, Any]:
        """The next key to try: one past the highest version or suffix the authority's siblings use."""
        key = rule.version_key if how == "version_up" else rule.suffix_key
        siblings = {k: v for k, v in fields.items() if k != key}
        taken = [e.fields[key] for e in authority.query(rule.name, siblings) if key in e.fields]
        # The first suffix is 2, beside the name without one.
        start = fields.get(key, 1)
        return {**fields, key: max([start, *taken]) + 1}

    def _forward(
        self,
        rule: Rule,
        links: Links,
        record: Record,
        operation: str,
        content: bytes | None,
        *,
        start: int = 0,
        retry: bool = False,
    ) -> Record:
        """Realize the active links from start, in order, then commit.

        A retry never rolls back: the record was already kept, so a failure
        leaves it out of sync again.
        """
        authority = self.stores[links.authority.name]
        active = links.active
        for index in range(start, len(active)):
            link = active[index]
            try:
                self._realize(link, authority, record, operation, content)
            except Exception as exc:
                if link.rollback and not retry:
                    return self._rollback(rule, links, record, operation, index, exc, f"link {link.name!r} failed")
                lagging = [link.name for link in active[index:]]
                kept = self._settle(authority, operation, record, "out_of_sync", lagging, exc)
                raise OutOfSyncError(
                    f"rule {rule.name!r}: link {link.name!r} failed, so record {record.id} is kept "
                    f"out of sync with {lagging} behind: {exc}",
                    kept,
                ) from exc
        try:
            self.checkpoint("settle:committed")
            return authority.settle(operation, record.id, "committed")
        except Exception as exc:
            if retry:
                raise OutOfSyncError(
                    f"rule {rule.name!r}: record {record.id} could not be committed, so it stays out of sync: {exc}",
                    self._current(authority, record),
                ) from exc
            if all(link.rollback for link in active):
                return self._rollback(rule, links, record, operation, len(active) - 1, exc, "the commit failed")
            # Every link is done, and one of them must not be undone, so recovery commits instead.
            raise WriteIncompleteError(
                f"rule {rule.name!r}: the commit failed after every link was realized, and a link has rollback "
                f"off, so record {record.id} is left pending for recovery to commit: {exc}",
                self._current(authority, record),
            ) from exc

    def _realize(self, link: Link, authority: Backend, record: Record, operation: str, content: bytes | None) -> None:
        def note(item: dict[str, Any]) -> None:
            authority.log(operation, record.id, "item", link=link.name, detail=item)
            self.checkpoint(f"{link.name}:{item['make']}")

        self.checkpoint(f"realize:{link.name}")
        self.stores[link.name].realize(record, content=content, note=note)
        self.checkpoint(f"realized:{link.name}")
        authority.log(operation, record.id, "realized", link=link.name)

    def _rollback(
        self,
        rule: Rule,
        links: Links,
        record: Record,
        operation: str,
        last: int,
        cause: Exception,
        reason: str,
    ) -> Record:
        """Undo links last down to the first, then mark the record failed. Always raises a WriteError."""
        authority = self.stores[links.authority.name]
        try:
            authority.log(operation, record.id, "rolling_back", detail={"reason": f"{reason}: {cause}"})
        except Exception as exc:
            raise WriteIncompleteError(
                f"rule {rule.name!r}: {reason} and the rollback could not start, so record {record.id} "
                f"is left pending for recovery: {exc}",
                self._current(authority, record),
            ) from cause
        steps = [s for s in authority.history(record.id) if s.operation == operation]
        for index in range(last, -1, -1):
            link = links.active[index]
            items = [s.detail for s in steps if s.step == "item" and s.link == link.name]
            try:
                self.checkpoint(f"undo:{link.name}")
                self.stores[link.name].undo(record, items)
                authority.log(operation, record.id, "undone", link=link.name)
            except Exception as exc:
                lagging = [link.name for link in links.active[index:]]
                kept = self._settle(authority, operation, record, "out_of_sync", lagging, cause)
                raise OutOfSyncError(
                    f"rule {rule.name!r}: {reason}, and link {link.name!r} could not be undone ({exc}), "
                    f"so record {record.id} is kept out of sync with {lagging} behind: {cause}",
                    kept,
                ) from cause
        failed = self._settle(authority, operation, record, "failed", (), cause)
        raise WriteRolledBackError(
            f"rule {rule.name!r}: {reason}, so the write was undone and record {record.id} is marked failed: {cause}",
            failed,
        ) from cause

    def _settle(
        self,
        authority: Backend,
        operation: str,
        record: Record,
        state: str,
        lagging: list[str] | tuple,
        cause: Exception,
    ) -> Record:
        """Settle after a failure. If even that fails, the record stays pending and recovery takes over."""
        try:
            self.checkpoint(f"settle:{state}")
            return authority.settle(operation, record.id, state, lagging=lagging)
        except Exception as exc:
            raise WriteIncompleteError(
                f"record {record.id} could not be marked {state}, so it is left {record.state} for recovery: {exc}",
                self._current(authority, record),
            ) from cause

    def _recover(self, record: Record, content: bytes | None = None) -> Record:
        rule = self.layout.rule(record.rule)
        links = self._links(rule)
        authority = self.stores[links.authority.name]
        operation, steps = _latest(authority.history(record.id))
        if record.state == "pending":
            started = [s for s in steps if s.step == "rolling_back"]
            if started:
                cause = WriteIncompleteError(started[0].detail.get("reason", "a rollback was interrupted"), record)
                last = len(links.active) - 1
                return self._rollback(rule, links, record, operation, last, cause, "recovery finished a rollback")
            return self._forward(rule, links, record, operation, content)
        names = [link.name for link in links.active]
        unknown = [name for name in record.lagging if name not in names]
        if unknown:
            raise LayoutError(
                f"record {record.id}: lagging links {unknown} are no longer active links of {rule.name!r}"
            )
        start = names.index(record.lagging[0])
        return self._forward(rule, links, record, operation, content, start=start, retry=True)

    @staticmethod
    def _current(authority: Backend, record: Record) -> Record:
        try:
            return authority.record(record.id)
        except Exception:
            return record

    @staticmethod
    def _find(authority: Backend, record: str) -> Record | None:
        try:
            return authority.record(record)
        except NoRecordError:
            return None

    # Holding

    def _hold(
        self,
        rule: Rule,
        links: Links,
        fields: Mapping[str, Any],
        attributes: Mapping[str, Any] | None,
        content: bytes | None,
    ) -> Entity:
        holding = self._holding()
        authority = self.stores[links.authority.name]
        attributes = authority._write_attributes(rule, attributes)
        full = full_fields(self.layout, rule, fields)
        parent = self._held_parent(holding, rule, full)
        self.checkpoint("hold")
        element = holding.hold(rule.name, full, attributes, content, parent=parent)
        return element.entity(self.layout.locate(rule.name, element.fields, authority.name))

    def _held_parent(self, holding: Holding, rule: Rule, fields: Mapping[str, Any]) -> str | None:
        """The nearest ancestor this owner holds, whose final key the element must wait for."""
        own = holding.elements(owners=[holding.owner])
        for ancestor in self._ancestors(rule):
            wanted = {k: v for k, v in fields.items() if k in ancestor.keys}
            for element in own:
                if element.rule == ancestor.name and element.fields == wanted:
                    return element.id
        return None

    def _overlay(
        self,
        rule: Rule,
        authority: Backend,
        fields: Mapping[str, Any] | None,
        attributes: Mapping[str, Any] | None,
    ) -> list[Entity]:
        bound = authority._query_fields(rule, fields)
        held = []
        for element in self._holding().elements(owners=[self.holding.owner]):
            if element.rule != rule.name or any(element.fields.get(k) != v for k, v in bound.items()):
                continue
            if any(element.attributes.get(k, _ABSENT) != v for k, v in (attributes or {}).items()):
                continue
            held.append(element.entity(self.layout.locate(rule.name, element.fields, authority.name)))
        return held

    def _merge(self, holding: Holding, element: Element, confirmed: bool, now: dt.datetime) -> MergeResult:
        rule = self.layout.rule(element.rule)
        links = self._links(rule)
        if not confirmed:
            waiting = _awaiting(links.authority, element, now)
            if waiting is not None:
                return MergeResult(element, "awaiting_confirmation", reason=waiting)
        try:
            fields = self._rebase(holding, rule, element)
        except (_Stop, UnreachableError) as exc:
            return _unmerged(element, exc)
        self.checkpoint("claim")
        if not holding.claim(element, self.claimant):
            return MergeResult(element, "claimed", reason=f"claimed by {holding.claimant(element)!r}")
        try:
            record = self._merge_write(holding, rule, links, element, fields)
        except Exception as exc:
            holding.release(element, self.claimant)
            return _unmerged(element, exc)
        try:
            self.checkpoint("clear")
            holding.remove(element)
        except Exception as exc:
            holding.release(element, self.claimant)
            return MergeResult(element, "incomplete", record, f"merged, but not yet removed from holding: {exc}")
        return MergeResult(element, "rekeyed" if record.requested else "merged", record)

    def _merge_write(
        self,
        holding: Holding,
        rule: Rule,
        links: Links,
        element: Element,
        fields: Mapping[str, Any],
    ) -> Record:
        """Write an element under its uuid, or finish the record an earlier merge of it left."""
        authority = self.stores[links.authority.name]
        content = holding.content(element)
        existing = self._find(authority, element.id)
        if existing is None or existing.state == "failed":
            operation = str(uuid.uuid4())
            attributes = element.attributes
            record = self._reserve(
                rule, links, operation, fields, attributes, content, record_id=element.id, requested=element.fields
            )
            return self._forward(rule, links, record, operation, content)
        if existing.state == "committed":
            return existing
        self.checkpoint("claim")
        if not authority.claim(existing.id, self.claimant):
            raise _Stop("claimed", f"record {existing.id} is {existing.state}, and another claimant is settling it")
        try:
            return self._recover(existing, content)
        finally:
            authority.release(existing.id, self.claimant)

    def _rebase(self, holding: Holding, rule: Rule, element: Element) -> dict[str, Any]:
        """The element's fields, with its held parent's final key in place of the one it asked for."""
        if element.parent is None:
            return element.fields
        if holding.has(element.parent):
            raise _Stop("blocked", f"its parent, held element {element.parent}, has not merged yet")
        for ancestor in self._ancestors(rule):
            if ancestor.links is None:
                continue
            parent = self._find(self.stores[ancestor.links.authority.name], element.parent)
            if parent is not None and parent.rule == ancestor.name:
                break
        else:
            raise _Stop("needs_decision", f"its parent {element.parent} is neither held nor in an authority")
        if parent.state == "pending":
            raise _Stop("blocked", f"its parent's record {parent.id} is pending, until recovery settles it")
        if parent.state == "failed":
            raise _Stop("needs_decision", f"its parent's record {parent.id} failed")
        fields = {k: v for k, v in element.fields.items() if k not in ancestor.keys}
        fields.update(parent.fields)
        return fields

    # Configuration

    def _holding(self) -> Holding:
        if self.holding is None:
            raise ConfigError("this engine has no holding area; pass holding= to the Engine")
        return self.holding

    def _ancestors(self, rule: Rule) -> list[Rule]:
        """Parent first, then its parent, and so on."""
        found = []
        while rule.parent is not None:
            rule = self.layout.rule(rule.parent)
            found.append(rule)
        return found

    def _linked_rules(self) -> list[Rule]:
        return [rule for rule in self.layout.rules.values() if rule.links is not None]

    def _links(self, rule: Rule) -> Links:
        if rule.links is None:
            raise ConfigError(f"rule {rule.name!r} has no links, so it has no authority to write to")
        return rule.links

    def _check(self, rule: Rule, links: Links) -> None:
        """Fail now on any binding or setting this engine cannot carry out."""
        context = f"rule {rule.name!r}"
        bound = [id(self.stores[link.name]) for link in links if link.name in self.stores]
        if len(set(bound)) != len(bound):
            raise ConfigError(f"{context}: one backend is bound to more than one of its links")
        passive = [(link, ("realize",)) for link in links.passive if link.name in self.stores]
        needs = [(links.authority, AUTHORITY_OPERATIONS), *((a, LINK_OPERATIONS) for a in links.active), *passive]
        for link, needed in needs:
            backend = self.stores.get(link.name)
            if backend is None:
                raise ConfigError(f"{context}: {link.role} link {link.name!r} is not bound to a backend")
            # A passive link realizes a committed record, whose key can no longer change.
            if link.role == "passive" and link.clash != "fail":
                raise ConfigError(
                    f"{context}: passive link {link.name!r} has clash rule {link.clash!r}, but a passive link "
                    f"can only fail on a clash, as the record it copies is already committed"
                )
            if backend.name not in rule.templates:
                raise ConfigError(
                    f"{context}: link {link.name!r} is {backend!r}, but the rule has no {backend.name!r} template"
                )
            missing = [op for op in needed if not backend.supports(op)]
            # An active link finds clashes before the write, so its clash rule can pick another key.
            if link.role == "active" and link.clash != "fail" and not backend.supports("clash"):
                missing.append("clash")
            # A clash rule reads the authority to find the next free version or suffix.
            if link.clash != "fail" and not self.stores[links.authority.name].supports("query"):
                missing.append(f"query on the authority, for clash rule {link.clash!r}")
            if missing:
                raise OperationNotSupportedError(
                    f"{context}: {backend!r} cannot be the {link.role} link {link.name!r}; it lacks {missing}"
                )
        if links.authority.offline == "hold" and self.holding is None:
            raise ConfigError(
                f"{context}: offline policy 'hold' on {links.authority.name!r} needs a holding area; "
                f"pass holding= to the Engine"
            )


_ABSENT = object()


def _latest(steps: list[Step]) -> tuple[str, list[Step]]:
    """The operation that last reserved a record, and its steps. A merge retried after a rollback reserves again."""
    operation = [s for s in steps if s.step == "reserved"][-1].operation
    return operation, [s for s in steps if s.operation == operation]


def _awaiting(authority: Link, element: Element, now: dt.datetime) -> str | None:
    """Why an element needs a person to confirm its merge (decision 0015), or None."""
    if authority.merge == "confirm":
        return f"rule {element.rule!r} merges held work only when a person confirms it"
    if authority.max_age is not None and now - element.held > authority.max_age:
        return f"held since {element.held.isoformat()}, longer than its max_age of {authority.max_age}"
    return None


def _unmerged(element: Element, exc: Exception) -> MergeResult:
    """The outcome of a merge that stopped. A clash under the rule fail needs a person; anything else is retried."""
    if isinstance(exc, _Stop):
        return MergeResult(element, exc.outcome, reason=str(exc))
    if isinstance(exc, (EntityExistsError, ClashError)):
        return MergeResult(element, "needs_decision", reason=str(exc))
    if isinstance(exc, WriteError):
        outcome = "needs_decision" if isinstance(exc.__cause__, ClashError) else "incomplete"
        return MergeResult(element, outcome, exc.record, str(exc))
    if isinstance(exc, LayoutError):
        return MergeResult(element, "incomplete", reason=str(exc))
    raise exc


def _parents_first(elements: list[Element]) -> list[Element]:
    """Elements in owner and sequence order, with each held parent moved before its children."""
    by_id = {e.id: e for e in elements}
    ordered: list[Element] = []
    seen: set[str] = set()

    def visit(element: Element) -> None:
        if element.id in seen:
            return
        seen.add(element.id)
        if element.parent in by_id:
            visit(by_id[element.parent])
        ordered.append(element)

    for element in elements:
        visit(element)
    return ordered
