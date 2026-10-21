"""The write flow: reserve in the authority, realize the active links in order, then settle (decision 0013).

Every write ends in one of the record states the write lifecycle declares.
Committed means the authority and every active link agree. Out of sync means
the record is kept and some links are behind. Failed means the write was
undone. Pending means the write stopped part way, and ``recover`` finishes or
undoes it from the operation log.

The flow is a list of named steps, and the engine calls ``checkpoint`` with
each name just before the step runs. Raising an exception there is how tests
make a step fail.

| Step | When |
| --- | --- |
| ``reserve`` | Before the authority records the entity as pending |
| ``realize:<link>`` | Before an active link starts |
| ``<link>:<item>`` | Before a link makes one item, such as ``files:dir``, once the item is in the log |
| ``realized:<link>`` | After a link has made everything |
| ``undo:<link>`` | Before a link's items are removed during a rollback |
| ``settle:<state>`` | Before the authority moves the record to committed, out_of_sync or failed |
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from .backends.base import AUTHORITY_OPERATIONS, LINK_OPERATIONS, Backend
from .entity import Entity
from .errors import (
    ConfigError,
    LayoutError,
    OperationNotSupportedError,
    OutOfSyncError,
    ReadOnlyError,
    UnreachableError,
    WriteError,
    WriteIncompleteError,
    WriteRolledBackError,
)
from .layout import Layout, Rule
from .links import Link, Links
from .records import Record, content_hash

Checkpoint = Callable[[str], None]


def _no_checkpoint(step: str) -> None:
    pass


class Engine:
    """Writes entities through their authority and active links, and reads them from the authority.

    ``stores`` binds each link name in the layout's links section to a
    backend. Every authority and active link must be bound. Passive links run
    only on their triggers, which a later phase adds, so they may be left out.
    """

    def __init__(self, layout: Layout, stores: Mapping[str, Backend], *, checkpoint: Checkpoint | None = None) -> None:
        self.layout = layout
        self.stores = dict(stores)
        self.checkpoint = checkpoint or _no_checkpoint
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
        """
        r = self.layout.rule(rule)
        links = self._links(r)
        authority = self.stores[links.authority.name]
        operation = str(uuid.uuid4())
        digest = content_hash(content) if content is not None else None
        try:
            self.checkpoint("reserve")
            record = authority.reserve(rule, fields, attributes, operation=operation, content_hash=digest)
        except UnreachableError as exc:
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
        """
        results = []
        authorities = {id(self.stores[r.links.authority.name]): r.links.authority.name for r in self._linked_rules()}
        for name in authorities.values():
            for record in self.stores[name].unsettled():
                try:
                    results.append(self._recover(record))
                except WriteError as exc:
                    results.append(exc.record)
        return results

    # Reads

    def query(
        self,
        rule: str,
        fields: Mapping[str, Any] | None = None,
        *,
        attributes: Mapping[str, Any] | None = None,
    ) -> list[Entity]:
        """Query the authority. If it is unreachable and the offline policy is read_only, query an active link."""
        links = self._links(self.layout.rule(rule))
        try:
            return self.stores[links.authority.name].query(rule, fields, attributes=attributes)
        except UnreachableError:
            if links.authority.offline != "read_only":
                raise
            for link in links.active:
                backend = self.stores[link.name]
                if backend.supports("query"):
                    return backend.query(rule, fields, attributes=attributes)
            raise

    def record(self, rule: str, record: str) -> Record:
        """A record from rule's authority, in any state."""
        return self.stores[self._links(self.layout.rule(rule)).authority.name].record(record)

    # The flow

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
        steps = authority.history(record.id)
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
        steps = authority.history(record.id)
        operation = steps[0].operation
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

    # Configuration

    def _linked_rules(self) -> list[Rule]:
        return [rule for rule in self.layout.rules.values() if rule.links is not None]

    def _links(self, rule: Rule) -> Links:
        if rule.links is None:
            raise ConfigError(f"rule {rule.name!r} has no links, so it has no authority to write to")
        return rule.links

    def _check(self, rule: Rule, links: Links) -> None:
        """Fail now on any binding or setting this engine cannot carry out."""
        context = f"rule {rule.name!r}"
        bound = [id(self.stores[link.name]) for link in (links.authority, *links.active) if link.name in self.stores]
        if len(set(bound)) != len(bound):
            raise ConfigError(f"{context}: one backend is bound to more than one of its links")
        for link, needed in ((links.authority, AUTHORITY_OPERATIONS), *((a, LINK_OPERATIONS) for a in links.active)):
            backend = self.stores.get(link.name)
            if backend is None:
                raise ConfigError(f"{context}: {link.role} link {link.name!r} is not bound to a backend")
            if backend.name not in rule.templates:
                raise ConfigError(
                    f"{context}: link {link.name!r} is {backend!r}, but the rule has no {backend.name!r} template"
                )
            missing = [op for op in needed if not backend.supports(op)]
            if missing:
                raise OperationNotSupportedError(
                    f"{context}: {backend!r} cannot be the {link.role} link {link.name!r}; it lacks {missing}"
                )
            if link.clash != "fail":
                raise OperationNotSupportedError(
                    f"{context}: link {link.name!r} has clash rule {link.clash!r}; only 'fail' is supported until merge"
                )
        if links.authority.offline == "hold":
            raise OperationNotSupportedError(
                f"{context}: offline policy 'hold' on {links.authority.name!r} needs holding, which is not built yet"
            )
