"""The backend interface.

The framework defines each operation and makes the call; a backend does the
work. A backend implements only the operations it can, and an operation it
does not implement fails when attempted. ``supported_operations`` lists what
a backend implements, so callers can check first.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..entity import Entity
from ..errors import LayoutError, OperationNotSupportedError
from ..layout import Layout, Rule

OPERATIONS = ("query", "exists")


class Backend:
    """A place where data lives, addressed through a layout's templates for one backend name."""

    def __init__(self, layout: Layout, name: str) -> None:
        self.layout = layout
        self.name = name

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"

    @classmethod
    def supported_operations(cls) -> frozenset[str]:
        """The operations this backend implements."""
        return frozenset(op for op in OPERATIONS if getattr(cls, op) is not getattr(Backend, op))

    @classmethod
    def supports(cls, operation: str) -> bool:
        return operation in cls.supported_operations()

    # Operations

    def query(
        self,
        rule: str,
        fields: Mapping[str, Any] | None = None,
        *,
        attributes: Mapping[str, Any] | None = None,
    ) -> list[Entity]:
        """Every entity of rule whose keys match fields; missing keys match anything."""
        raise self._unsupported("query")

    def exists(self, rule: str, fields: Mapping[str, Any]) -> bool:
        """Whether the entity named by a full set of fields exists."""
        raise self._unsupported("exists")

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
