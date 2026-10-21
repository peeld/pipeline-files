"""The SQLite backend: entities are rows in one table (decision 0011)."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from ..entity import Entity
from ..errors import ConfigError, EntityExistsError, InvalidValueError, LayoutError
from ..keys import Key
from ..layout import Layout, Rule
from ..location import Location
from .base import AttributeValidator, Backend

SCHEMA_VERSION = "1"
_COLUMN_TYPES = {"int": "INTEGER", "string": "TEXT", "date": "TEXT"}
# Attribute filters compare one top-level value; containers are refused before this runs.
_ATTRIBUTE_MATCH = (
    "EXISTS (SELECT 1 FROM json_each(entities.attributes) AS a"
    " WHERE a.key = ? AND a.type NOT IN ('object', 'array') AND a.value = ?)"
)


class SQLiteBackend(Backend):
    """Stores entities as rows of one ``entities`` table in an SQLite database.

    The backend is built for one template name, ``fs`` by default, and each
    row's location is its rule's template for that name, formatted from the
    row's fields. So a row read through the ``fs`` template has the same
    location the filesystem backend would give it. Queries compile to a
    WHERE clause with bound parameters, and every row read back is checked
    against its rule.
    """

    capabilities = frozenset({"attribute_queries", "atomic_updates"})

    def __init__(
        self,
        layout: Layout,
        path: str | os.PathLike,
        name: str = "fs",
        *,
        validator: AttributeValidator | None = None,
    ) -> None:
        super().__init__(layout, name, validator=validator)
        self.path = os.fspath(path)
        self._keys = self._stored_keys()
        try:
            self._conn = sqlite3.connect(self.path, isolation_level=None)
        except sqlite3.Error as exc:
            raise LayoutError(f"cannot open SQLite database {self.path!r}: {exc}") from None
        try:
            self._prepare()
        except sqlite3.DatabaseError as exc:
            self._conn.close()
            raise LayoutError(f"cannot use SQLite database {self.path!r}: {exc}") from None
        except LayoutError:
            self._conn.close()
            raise

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, {self.path!r})"

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SQLiteBackend:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group writes so they all happen or none do. Transactions nest."""
        self._conn.execute("SAVEPOINT entitylayout")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK TO entitylayout")
            self._conn.execute("RELEASE entitylayout")
            raise
        self._conn.execute("RELEASE entitylayout")

    # Operations

    def query(
        self,
        rule: str,
        fields: Mapping[str, Any] | None = None,
        *,
        attributes: Mapping[str, Any] | None = None,
    ) -> list[Entity]:
        filters = self._query_attributes(attributes)
        r = self._rule(rule)
        bound = self._query_fields(r, fields)
        clauses = ["rule = ?"]
        params: list[Any] = [r.name]
        for name, value in bound.items():
            clauses.append(f"{_column(name)} = ?")
            params.append(self._to_column(name, value))
        for name, value in filters.items():
            clauses.append(_ATTRIBUTE_MATCH)
            params.extend((name, _attribute_filter_value(r, name, value)))
        columns = ", ".join(_column(k) for k in r.keys)
        sql = f"SELECT id, location, attributes, {columns} FROM entities WHERE {' AND '.join(clauses)}"
        entities = [self._entity(r, row) for row in self._conn.execute(sql, params)]
        entities.sort(key=lambda e: e.location.path)
        return entities

    def exists(self, rule: str, fields: Mapping[str, Any]) -> bool:
        self._rule(rule)
        location = self.layout.locate(rule, fields, self.name)
        row = self._conn.execute(
            "SELECT 1 FROM entities WHERE rule = ? AND location = ?", (rule, location.path)
        ).fetchone()
        return row is not None

    def create(self, rule: str, fields: Mapping[str, Any], attributes: Mapping[str, Any] | None = None) -> Entity:
        r = self._rule(rule)
        location = self.layout.locate(rule, fields, self.name)
        # Read the location back, so stored fields include defaults and match what a query returns.
        full = r.template(self.name).parse(location.path)
        attributes = self._write_attributes(r, attributes)
        stored = _encode_attributes(r, attributes)
        # Decode before writing, so a value that would not read back fails now rather than on every query.
        attributes = _decode_attributes(r, stored, location)
        names = list(full)
        columns = ", ".join(["id", "rule", "location", "config_version", "attributes", *map(_column, names)])
        params = [str(uuid.uuid4()), r.name, location.path, str(self.layout.version), stored]
        params.extend(self._to_column(n, full[n]) for n in names)
        sql = f"INSERT INTO entities ({columns}) VALUES ({', '.join('?' * len(params))})"
        with self.transaction():
            try:
                self._conn.execute(sql, params)
            except sqlite3.IntegrityError:
                raise EntityExistsError(f"rule {r.name!r}: an entity already exists at {location.uri}") from None
        return Entity(r.name, full, location, attributes=attributes)

    # Schema

    def _stored_keys(self) -> dict[str, Key]:
        """Every key used by a rule with a template for this backend's name."""
        names = {k for rule in self.layout.rules.values() if self.name in rule.templates for k in rule.keys}
        # SQLite column names ignore case, so two keys that differ only in case would share a column.
        folded: dict[str, str] = {}
        for name in sorted(names):
            other = folded.setdefault(name.casefold(), name)
            if other != name:
                raise ConfigError(f"keys {other!r} and {name!r} differ only in case, so SQLite cannot store both")
        return {name: self.layout.keys[name] for name in sorted(names)}

    def _prepare(self) -> None:
        with self.transaction():
            self._conn.execute("CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            meta = dict(self._conn.execute("SELECT name, value FROM meta"))
            if not meta:
                self._conn.executemany(
                    "INSERT INTO meta (name, value) VALUES (?, ?)",
                    [("schema", SCHEMA_VERSION), ("template", self.name)],
                )
            elif meta.get("schema") != SCHEMA_VERSION:
                raise LayoutError(f"{self.path!r} has schema {meta.get('schema')!r}; expected {SCHEMA_VERSION!r}")
            elif meta.get("template") != self.name:
                raise LayoutError(
                    f"{self.path!r} holds locations for template {meta.get('template')!r}, not {self.name!r}"
                )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS entities ("
                " id TEXT PRIMARY KEY,"
                " rule TEXT NOT NULL,"
                " location TEXT NOT NULL,"
                " config_version TEXT NOT NULL,"
                " attributes TEXT NOT NULL DEFAULT '{}',"
                " UNIQUE (rule, location))"
            )
            existing = {row[1].casefold() for row in self._conn.execute("PRAGMA table_info(entities)")}
            for name, key in self._keys.items():
                if f"key_{name}".casefold() not in existing:
                    self._conn.execute(f"ALTER TABLE entities ADD COLUMN {_column(name)} {_COLUMN_TYPES[key.type]}")

    # Values

    def _to_column(self, name: str, value: Any) -> Any:
        if isinstance(value, dt.date):
            return value.isoformat()
        if isinstance(value, int) and not -(2**63) <= value < 2**63:
            raise InvalidValueError(f"{name}: {value} is too large for an SQLite INTEGER")
        return value

    def _from_column(self, name: str, value: Any) -> Any:
        if self.layout.keys[name].type == "date" and isinstance(value, str):
            return dt.date.fromisoformat(value)
        return value

    def _entity(self, rule: Rule, row: tuple) -> Entity:
        row_id, path, stored, *values = row
        location = Location(self.name, rule.root, path)
        try:
            fields = {k: self._from_column(k, v) for k, v in zip(rule.keys, values, strict=True) if v is not None}
            expected = rule.template(self.name).format(fields)
        except (LayoutError, ValueError) as exc:
            raise LayoutError(f"row {row_id} ({location.uri}) does not fit rule {rule.name!r}: {exc}") from None
        if expected != path:
            raise LayoutError(
                f"row {row_id}: stored location {path!r} does not match its fields, which give {expected!r}"
            )
        return Entity(rule.name, fields, location, attributes=_decode_attributes(rule, stored, location))


def _column(key: str) -> str:
    # Key names are letters, digits and '_', so quoting is only a guard against SQL keywords.
    return f'"key_{key}"'


def _encode_attributes(rule: Rule, attributes: Mapping[str, Any]) -> str:
    def default(value: Any) -> Any:
        if isinstance(value, dt.date):
            return value.isoformat()
        if isinstance(value, tuple):
            return list(value)
        raise TypeError(f"{type(value).__name__} is not JSON serializable")

    for name, value in attributes.items():
        try:
            json.dumps(value, default=default, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise InvalidValueError(f"rule {rule.name!r}: attribute {name!r} cannot be stored: {exc}") from None
    return json.dumps(attributes, default=default, allow_nan=False, ensure_ascii=False, sort_keys=True)


def _decode_attributes(rule: Rule, stored: str, location: Location) -> dict[str, Any]:
    """Attributes read back, with declared dates and datetimes turned back from ISO text."""
    try:
        attributes = json.loads(stored)
    except ValueError as exc:
        raise LayoutError(f"{location.uri}: attributes are not valid JSON: {exc}") from None
    if not isinstance(attributes, dict):
        raise LayoutError(f"{location.uri}: attributes must be a JSON object, got {stored!r}")
    for name, value in attributes.items():
        kind = rule.attributes.get(name)
        if kind not in ("date", "datetime") or not isinstance(value, str):
            continue
        try:
            attributes[name] = (dt.date if kind == "date" else dt.datetime).fromisoformat(value)
        except ValueError:
            raise LayoutError(f"{location.uri}: attribute {name!r} is declared {kind} but holds {value!r}") from None
    return attributes


def _attribute_filter_value(rule: Rule, name: str, value: Any) -> Any:
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (str, int, float)):
        return value
    raise InvalidValueError(
        f"rule {rule.name!r}: attribute filter {name!r} can only test equality to a string, number, "
        f"boolean or date, not {value!r}"
    )
