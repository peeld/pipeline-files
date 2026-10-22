"""The backend interface.

The framework defines each operation and makes the call; a backend does the
work. A backend implements only the operations it can, and an operation it
does not implement fails when attempted. ``supported_operations`` lists what
a backend implements, so callers can check first.

Capabilities describe how far an operation goes on a backend, such as
whether a query can filter by attributes. A backend declares them, because
they cannot be worked out from which methods it overrides.

A backend that keeps records with states and an operation log implements
the authority operations and can be an authority. One that can realize a
record idempotently and undo only what it made can be an active link. An
active link whose clash rule is not ``fail`` also needs ``clash``, so a
clash is found before anything is written. A passive link needs ``realize``
only, since it is never rolled back.

The migration operations let a site's script move a rule to a new authority
(decision 0018). The old authority claims the whole rule, which makes every
write to it there unreachable, and lists each record with its log. The new
one restores each record under its own ID.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..entity import Entity
from ..errors import LayoutError, OperationNotSupportedError
from ..layout import Layout, Rule
from ..records import Record, Step

AUTHORITY_OPERATIONS = ("reserve", "log", "settle", "record", "history", "unsettled", "claim", "release")
LINK_OPERATIONS = ("realize", "undo")
MIGRATION_OPERATIONS = ("claim_rule", "release_rule", "records", "restore")
OPERATIONS = ("query", "exists", "create", *AUTHORITY_OPERATIONS, *LINK_OPERATIONS, "clash", *MIGRATION_OPERATIONS)
CAPABILITIES = (
    # Queries can filter by attribute equality, including attributes the rule does not declare.
    "attribute_queries",
    # Several writes can be grouped so they all happen or none do.
    "atomic_updates",
)

# Checks a rule's attributes before they are written, raising LayoutError on a bad one.
AttributeValidator = Callable[[Rule, Mapping[str, Any]], None]
# Called by a link step before it makes each item, so the item is in the log before it exists.
Note = Callable[[dict[str, Any]], None]


class Backend:
    """A place where data lives, addressed through a layout's templates for one backend name.

    The core never checks attributes (decision 0005). A deployment that wants
    them checked passes a validator, which every write calls first.
    """

    capabilities: frozenset[str] = frozenset()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        unknown = sorted(set(cls.capabilities) - set(CAPABILITIES))
        if unknown:
            raise TypeError(f"{cls.__name__} declares unknown capabilities {unknown}; known: {list(CAPABILITIES)}")

    def __init__(self, layout: Layout, name: str, *, validator: AttributeValidator | None = None) -> None:
        self.layout = layout
        self.name = name
        self.validator = validator

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"

    @classmethod
    def supported_operations(cls) -> frozenset[str]:
        """The operations this backend implements."""
        return frozenset(op for op in OPERATIONS if getattr(cls, op) is not getattr(Backend, op))

    @classmethod
    def supports(cls, operation: str) -> bool:
        return operation in cls.supported_operations()

    @classmethod
    def has_capability(cls, capability: str) -> bool:
        if capability not in CAPABILITIES:
            raise LayoutError(f"unknown capability {capability!r}; known: {list(CAPABILITIES)}")
        return capability in cls.capabilities

    # Operations

    def query(
        self,
        rule: str,
        fields: Mapping[str, Any] | None = None,
        *,
        attributes: Mapping[str, Any] | None = None,
    ) -> list[Entity]:
        """Every entity of rule whose keys match fields; missing keys match anything.

        Attribute filters need the attribute_queries capability.
        """
        raise self._unsupported("query")

    def exists(self, rule: str, fields: Mapping[str, Any]) -> bool:
        """Whether the entity named by a full set of fields exists."""
        raise self._unsupported("exists")

    def create(self, rule: str, fields: Mapping[str, Any], attributes: Mapping[str, Any] | None = None) -> Entity:
        """Record a new entity from a full set of fields, failing if it already exists."""
        raise self._unsupported("create")

    # Authority operations

    def reserve(
        self,
        rule: str,
        fields: Mapping[str, Any],
        attributes: Mapping[str, Any] | None = None,
        *,
        operation: str,
        content_hash: str | None = None,
        record_id: str | None = None,
        requested: Mapping[str, Any] | None = None,
    ) -> Record:
        """Record a new entity as pending, logging the reservation in the same transaction.

        Fails with EntityExistsError if a record that has not failed holds the
        location. With record_id, the record takes that internal ID: a merge
        reserves under its holding uuid. That fails with RecordExistsError if
        a record that has not failed has the ID, and replaces a failed one,
        whose log is kept. With requested, the fields first asked for are kept
        beside the record's own.
        """
        raise self._unsupported("reserve")

    def log(
        self,
        operation: str,
        record: str,
        step: str,
        *,
        link: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """Append a step to the operation log."""
        raise self._unsupported("log")

    def settle(self, operation: str, record: str, state: str, *, lagging: Sequence[str] = ()) -> Record:
        """Move a record to a new state, logging the change in the same transaction."""
        raise self._unsupported("settle")

    def record(self, record: str) -> Record:
        """The record with an internal ID, in any state."""
        raise self._unsupported("record")

    def history(self, record: str) -> list[Step]:
        """Every logged step for a record, oldest first."""
        raise self._unsupported("history")

    def unsettled(self) -> list[Record]:
        """Records that recovery has to finish: pending and out of sync."""
        raise self._unsupported("unsettled")

    def claim(self, record: str, claimant: str) -> bool:
        """Claim a record for claimant by an atomic create. True if claimant holds it, now or already."""
        raise self._unsupported("claim")

    def release(self, record: str, claimant: str | None) -> None:
        """Drop claimant's claim on a record. With None, drop whoever holds it, as a person may."""
        raise self._unsupported("release")

    # Migration operations

    def claim_rule(self, rule: str, claimant: str) -> bool:
        """Claim a whole rule for claimant, as a migration does before it moves the rule away.

        While the claim holds, every write to the rule's records here raises
        UnreachableError, so the rule's offline policy applies. Reads still
        work. True if claimant holds the claim, now or already.
        """
        raise self._unsupported("claim_rule")

    def release_rule(self, rule: str, claimant: str | None) -> None:
        """Drop claimant's claim on a rule. With None, drop whoever holds it, as a person may."""
        raise self._unsupported("release_rule")

    def records(self, *rules: str) -> list[Record]:
        """Every record of the rules, in any state, in the order they were first logged.

        Restoring them in this order keeps the order recovery takes them in.
        """
        raise self._unsupported("records")

    def restore(self, record: Record, history: Sequence[Step]) -> Record:
        """Write a record from another authority with its own ID, state, revision, requested key and log.

        Running it again changes nothing. A record already here with that ID is
        accepted only if its log starts with history, and its fields match when
        nothing has been logged since. Anything else raises RecordExistsError,
        and a location taken by another record raises EntityExistsError.
        """
        raise self._unsupported("restore")

    # Link operations

    def realize(self, record: Record, *, content: bytes | None = None, note: Note) -> None:
        """Make the record exist here. Running it again changes nothing.

        Each item the step makes is passed to note first, so a later undo, even
        after a crash, knows everything this step may have made.
        """
        raise self._unsupported("realize")

    def clash(self, record: Record) -> str | None:
        """What would make realize fail with a clash for this record, or None. It changes nothing."""
        raise self._unsupported("clash")

    def undo(self, record: Record, items: Sequence[Mapping[str, Any]]) -> None:
        """Remove the items a realize made for record, newest first, and nothing else.

        Items already gone are skipped. Raises UndoError for an item that has
        changed since, or that holds something this step did not make.
        """
        raise self._unsupported("undo")

    # Helpers for implementations

    def _unsupported(self, operation: str) -> OperationNotSupportedError:
        return OperationNotSupportedError(f"{self!r} does not support {operation!r}")

    def _rule(self, name: str) -> Rule:
        rule = self.layout.rule(name)
        if self.name not in rule.templates:
            raise LayoutError(f"rule {name!r} has no template for backend {self.name!r}")
        return rule

    def _query_fields(self, rule: Rule, fields: Mapping[str, Any] | None) -> dict[str, Any]:
        """Check query fields against the rule and its keys, dropping any left as None."""
        given = {k: v for k, v in (fields or {}).items() if v is not None}
        unknown = sorted(set(given) - set(rule.keys))
        if unknown:
            raise LayoutError(f"rule {rule.name!r} has no keys {unknown}")
        return {k: self.layout.keys[k].validate(v) for k, v in given.items()}

    def _query_attributes(self, attributes: Mapping[str, Any] | None) -> dict[str, Any]:
        """Check that this backend can filter by attributes, if any are given."""
        if attributes and "attribute_queries" not in self.capabilities:
            raise self._unsupported("query by attributes")
        return dict(attributes or {})

    def _write_attributes(self, rule: Rule, attributes: Mapping[str, Any] | None) -> dict[str, Any]:
        """Attributes ready to write, after the optional validator has seen them."""
        attributes = dict(attributes or {})
        clashes = sorted(set(attributes) & set(rule.keys))
        if clashes:
            raise LayoutError(f"rule {rule.name!r}: {clashes} are keys, so they cannot also be attributes")
        if self.validator is not None:
            self.validator(rule, attributes)
        return attributes
