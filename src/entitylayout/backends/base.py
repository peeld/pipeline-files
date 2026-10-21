"""The backend interface.

The framework defines each operation and makes the call; a backend does the
work. A backend implements only the operations it can, and an operation it
does not implement fails when attempted. ``supported_operations`` lists what
a backend implements, so callers can check first.

Capabilities describe how far an operation goes on a backend, such as
whether a query can filter by attributes. A backend declares them, because
they cannot be worked out from which methods it overrides.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..entity import Entity
from ..errors import LayoutError, OperationNotSupportedError
from ..layout import Layout, Rule

OPERATIONS = ("query", "exists", "create")
CAPABILITIES = (
    # Queries can filter by attribute equality, including attributes the rule does not declare.
    "attribute_queries",
    # Several writes can be grouped so they all happen or none do.
    "atomic_updates",
)

# Checks a rule's attributes before they are written, raising LayoutError on a bad one.
AttributeValidator = Callable[[Rule, Mapping[str, Any]], None]


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
