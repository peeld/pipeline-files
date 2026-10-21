"""Queries and the small, composable filters applied to their results.

A filter takes an iterable of results and returns a list of results, so
filters chain in any order::

    Query("media", {"shot": 40}).then(newest("version"), sort_by("camera")).run(backend)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .backends.base import Backend
from .entity import Entity

Filter = Callable[[Iterable[Any]], list[Any]]


@dataclass(frozen=True)
class Query:
    """A rule, some fields, optional attribute filters, and filters to apply to the results."""

    rule: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] | None = None
    filters: tuple[Filter, ...] = ()

    def then(self, *filters: Filter) -> Query:
        """A copy of this query with more filters applied after the existing ones."""
        return Query(self.rule, self.fields, self.attributes, (*self.filters, *filters))

    def run(self, backend: Backend) -> list[Any]:
        results: list[Any] = backend.query(self.rule, self.fields, attributes=self.attributes)
        for apply in self.filters:
            results = apply(results)
        return results


def where(predicate: Callable[[Entity], bool]) -> Filter:
    """Keep the results for which predicate is true."""

    def apply(results: Iterable[Entity]) -> list[Entity]:
        return [r for r in results if predicate(r)]

    return apply


def newest(key: str = "version", *, within: Iterable[str] | None = None) -> Filter:
    """Keep only the highest value of key in each group.

    Groups are results of the same rule that agree on every other key, or on
    just the keys in within when it is given. Results without the key are
    kept as they are.
    """
    within = tuple(within) if within is not None else None

    def apply(results: Iterable[Entity]) -> list[Entity]:
        # Dicts keep first-insertion order, so each group stays where it first appeared.
        best: dict[tuple, Entity] = {}
        for i, entity in enumerate(results):
            if key not in entity.fields:
                best[(None, i)] = entity
                continue
            names = within if within is not None else sorted(k for k in entity.fields if k != key)
            group = (entity.rule, *((n, entity.fields.get(n)) for n in names))
            current = best.get(group)
            if current is None or entity.fields[key] > current.fields[key]:
                best[group] = entity
        return list(best.values())

    return apply


def sort_by(*keys: str, reverse: bool = False) -> Filter:
    """Sort by the given keys in turn. Results missing a key sort before those that have it."""

    def sort_key(entity: Entity) -> tuple:
        return tuple((0,) if k not in entity.fields else (1, entity.fields[k]) for k in keys)

    def apply(results: Iterable[Entity]) -> list[Entity]:
        return sorted(results, key=sort_key, reverse=reverse)

    return apply


def group_by(results: Iterable[Entity], *keys: str) -> dict[tuple, list[Entity]]:
    """Group results by the values of keys, in order of first appearance. Missing keys group as None."""
    groups: dict[tuple, list[Entity]] = {}
    for entity in results:
        groups.setdefault(tuple(entity.fields.get(k) for k in keys), []).append(entity)
    return groups


@dataclass(frozen=True)
class EntitySequence:
    """Entities that differ only in one numbered key, such as the frames of a render."""

    rule: str
    fields: dict[str, Any]
    key: str
    values: tuple[int, ...]
    entities: tuple[Entity, ...]

    def ranges(self) -> list[tuple[int, int]]:
        """The values as runs of consecutive numbers, each as (first, last)."""
        runs: list[tuple[int, int]] = []
        for value in self.values:
            if runs and value == runs[-1][1] + 1:
                runs[-1] = (runs[-1][0], value)
            else:
                runs.append((value, value))
        return runs

    def __str__(self) -> str:
        return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in self.ranges())


def collapse_sequence(key: str = "frame") -> Filter:
    """Replace entities that differ only in key with one EntitySequence.

    Entities without the key pass through unchanged.
    """

    def apply(results: Iterable[Entity]) -> list[Any]:
        out: list[Any] = []
        groups: dict[tuple, list[Entity]] = {}
        for entity in results:
            if key not in entity.fields:
                out.append(entity)
                continue
            rest = {k: v for k, v in entity.fields.items() if k != key}
            group = (entity.rule, tuple(sorted(rest.items())))
            if group not in groups:
                groups[group] = []
                out.append(group)
            groups[group].append(entity)
        collapsed = []
        for item in out:
            if isinstance(item, Entity):
                collapsed.append(item)
                continue
            members = sorted(groups[item], key=lambda e: e.fields[key])
            collapsed.append(
                EntitySequence(
                    rule=item[0],
                    fields=dict(item[1]),
                    key=key,
                    values=tuple(e.fields[key] for e in members),
                    entities=tuple(members),
                )
            )
        return collapsed

    return apply
