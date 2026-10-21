"""Entities: what a query returns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .location import Location


@dataclass(frozen=True)
class Entity:
    """One entity: its rule, its full fields, where it was found, and its attributes.

    A location is not a real path. Ask the layout for the real path when a
    tool actually needs to open something.
    """

    rule: str
    fields: dict[str, Any]
    location: Location
    # True for entities still in holding, not yet merged into the authority.
    provisional: bool = False
    # Empty on backends that do not store attributes.
    attributes: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.fields[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)
