"""The SQLite backend: entities are rows in one table (decision 0011), with states and an operation log (0013)."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from ..entity import Entity
from ..errors import ConfigError, EntityExistsError, InvalidValueError, LayoutError
from ..keys import Key
from ..layout import Layout, Rule
from ..location import Location
from ..records import STATES, VISIBLE_STATES, Record, Step, canonical_json, json_default
from .base import AttributeValidator, Backend

SCHEMA_VERSION = "2"
# The fixed columns of the entities table. Key columns follow, one per key.
_ENTITIES_TABLE = (
    "CREATE TABLE entities ("
    " id TEXT PRIMARY KEY,"
    " rule TEXT NOT NULL,"
    " location TEXT NOT NULL,"
    " config_version TEXT NOT NULL,"
    " attributes TEXT NOT NULL DEFAULT '{}',"
    f" state TEXT NOT NULL DEFAULT 'committed' CHECK (state IN ({', '.join(repr(s) for s in STATES)})),"
    " revision INTEGER NOT NULL DEFAULT 1,"
    " content_hash TEXT,"
    " lagging TEXT NOT NULL DEFAULT '[]')"
)
_V1_COLUMNS = ("id", "rule", "location", "config_version", "attributes")
_VISIBLE = f"state IN ({', '.join(repr(s) for s in VISIBLE_STATES)})"
# The states a record may move to from each state. A failed record is final, so its location can be reused.
_SETTLE_FROM = {"pending": {"committed", "out_of_sync", "failed"}, "out_of_sync": {"committed", "out_of_sync"}}
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

    Each row is a record with a state. Normal queries see committed and out
    of sync records only. The operation log is written in the same
    transaction as each change to a record, so SQLite can be an authority.
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
        clauses = ["rule = ?", _VISIBLE]
        params: list[Any] = [r.name]
        for name, value in bound.items():
            clauses.append(f"{_column(name)} = ?")
            params.append(self._to_column(name, value))
        for name, value in filters.items():
            clauses.append(_ATTRIBUTE_MATCH)
            params.extend((name, _attribute_filter_value(r, name, value)))
        sql = f"SELECT {self._select(r)} FROM entities WHERE {' AND '.join(clauses)}"
        entities = [self._record(r, row).entity() for row in self._conn.execute(sql, params)]
        entities.sort(key=lambda e: e.location.path)
        return entities

    def exists(self, rule: str, fields: Mapping[str, Any]) -> bool:
        self._rule(rule)
        location = self.layout.locate(rule, fields, self.name)
        row = self._conn.execute(
            f"SELECT 1 FROM entities WHERE rule = ? AND location = ? AND {_VISIBLE}", (rule, location.path)
        ).fetchone()
        return row is not None

    def create(self, rule: str, fields: Mapping[str, Any], attributes: Mapping[str, Any] | None = None) -> Entity:
        """Record a committed entity directly, with no links. The log records it as one step."""
        return self._insert(rule, fields, attributes, "committed", str(uuid.uuid4()), None).entity()

    # Authority operations

    def reserve(
        self,
        rule: str,
        fields: Mapping[str, Any],
        attributes: Mapping[str, Any] | None = None,
        *,
        operation: str,
        content_hash: str | None = None,
    ) -> Record:
        return self._insert(rule, fields, attributes, "pending", operation, content_hash)

    def log(
        self,
        operation: str,
        record: str,
        step: str,
        *,
        link: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO operations (operation, record, step, link, detail) VALUES (?, ?, ?, ?, ?)",
            (operation, record, step, link, canonical_json(dict(detail or {}))),
        )

    def settle(self, operation: str, record: str, state: str, *, lagging: Sequence[str] = ()) -> Record:
        current = self.record(record)
        if state not in _SETTLE_FROM.get(current.state, ()):
            raise LayoutError(f"record {record} ({current.location.uri}) cannot move from {current.state} to {state}")
        if (state == "out_of_sync") != bool(lagging):
            raise LayoutError(f"record {record}: lagging links are given exactly when it is out of sync")
        with self.transaction():
            self._conn.execute(
                "UPDATE entities SET state = ?, lagging = ? WHERE id = ?", (state, json.dumps(list(lagging)), record)
            )
            self.log(operation, record, state, detail={"lagging": list(lagging)} if lagging else None)
        return self.record(record)

    def record(self, record: str) -> Record:
        row = self._conn.execute("SELECT rule FROM entities WHERE id = ?", (record,)).fetchone()
        if row is None:
            raise LayoutError(f"{self.path!r} has no record {record}")
        rule = self.layout.rule(row[0])
        found = self._conn.execute(f"SELECT {self._select(rule)} FROM entities WHERE id = ?", (record,)).fetchone()
        return self._record(rule, found)

    def history(self, record: str) -> list[Step]:
        rows = self._conn.execute(
            "SELECT seq, operation, record, step, link, detail FROM operations WHERE record = ? ORDER BY seq",
            (record,),
        )
        return [Step(seq, op, rec, step, link, json.loads(detail)) for seq, op, rec, step, link, detail in rows]

    def unsettled(self) -> list[Record]:
        rows = self._conn.execute(
            "SELECT entities.id FROM entities JOIN operations ON operations.record = entities.id"
            " WHERE entities.state IN ('pending', 'out_of_sync') GROUP BY entities.id ORDER BY MIN(operations.seq)"
        )
        return [self.record(row_id) for (row_id,) in rows.fetchall()]

    def _insert(
        self,
        rule: str,
        fields: Mapping[str, Any],
        attributes: Mapping[str, Any] | None,
        state: str,
        operation: str,
        content_hash: str | None,
    ) -> Record:
        r = self._rule(rule)
        location = self.layout.locate(rule, fields, self.name)
        # Read the location back, so stored fields include defaults and match what a query returns.
        full = r.template(self.name).parse(location.path)
        attributes = self._write_attributes(r, attributes)
        stored = _encode_attributes(r, attributes)
        # Decode before writing, so a value that would not read back fails now rather than on every query.
        attributes = _decode_attributes(r, stored, location)
        record = Record(
            id=str(uuid.uuid4()),
            rule=r.name,
            fields=full,
            location=location,
            state=state,
            revision=1,
            config_version=str(self.layout.version),
            attributes=attributes,
            content_hash=content_hash,
        )
        names = list(full)
        columns = ["id", "rule", "location", "config_version", "attributes", "state", "revision", "content_hash"]
        params = [record.id, r.name, location.path, record.config_version, stored, state, 1, content_hash]
        params.extend(self._to_column(n, full[n]) for n in names)
        sql = (
            f"INSERT INTO entities ({', '.join([*columns, *map(_column, names)])})"
            f" VALUES ({', '.join('?' * len(params))})"
        )
        with self.transaction():
            try:
                self._conn.execute(sql, params)
            except sqlite3.IntegrityError:
                raise EntityExistsError(f"rule {r.name!r}: an entity already exists at {location.uri}") from None
            self.log(operation, record.id, "reserved" if state == "pending" else state, detail={"kind": "create"})
        return record

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
                self._conn.execute(_ENTITIES_TABLE)
                self._create_indexes()
            elif meta.get("schema") not in ("1", SCHEMA_VERSION):
                raise LayoutError(f"{self.path!r} has schema {meta.get('schema')!r}; expected {SCHEMA_VERSION!r}")
            elif meta.get("template") != self.name:
                raise LayoutError(
                    f"{self.path!r} holds locations for template {meta.get('template')!r}, not {self.name!r}"
                )
            elif meta.get("schema") == "1":
                self._upgrade_from_1()
            existing = {row[1].casefold() for row in self._conn.execute("PRAGMA table_info(entities)")}
            for name, key in self._keys.items():
                if f"key_{name}".casefold() not in existing:
                    self._conn.execute(f"ALTER TABLE entities ADD COLUMN {_column(name)} {_COLUMN_TYPES[key.type]}")

    def _create_indexes(self) -> None:
        # Failed records stay for the log, so they must not keep their location from being used again.
        self._conn.execute("CREATE UNIQUE INDEX entities_location ON entities (rule, location) WHERE state != 'failed'")
        self._conn.execute(
            "CREATE TABLE operations ("
            " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
            " operation TEXT NOT NULL,"
            " record TEXT NOT NULL,"
            " step TEXT NOT NULL,"
            " link TEXT,"
            " detail TEXT NOT NULL DEFAULT '{}')"
        )
        self._conn.execute("CREATE INDEX operations_record ON operations (record, seq)")

    def _upgrade_from_1(self) -> None:
        """Rebuild the entities table with states, and add the operation log. Version 1 rows are committed."""
        old = [(row[1], row[2]) for row in self._conn.execute("PRAGMA table_info(entities)")]
        keys = [(name, kind) for name, kind in old if name not in _V1_COLUMNS]
        self._conn.execute("ALTER TABLE entities RENAME TO entities_v1")
        self._conn.execute(_ENTITIES_TABLE)
        for name, kind in keys:
            self._conn.execute(f'ALTER TABLE entities ADD COLUMN "{name}" {kind}')
        columns = ", ".join(f'"{name}"' for name, _ in old)
        self._conn.execute(f"INSERT INTO entities ({columns}) SELECT {columns} FROM entities_v1")
        self._conn.execute("DROP TABLE entities_v1")
        self._create_indexes()
        self._conn.execute("UPDATE meta SET value = ? WHERE name = 'schema'", (SCHEMA_VERSION,))

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

    def _select(self, rule: Rule) -> str:
        fixed = "id, location, attributes, state, revision, config_version, content_hash, lagging"
        return ", ".join([fixed, *map(_column, rule.keys)])

    def _record(self, rule: Rule, row: tuple) -> Record:
        row_id, path, stored, state, revision, config_version, content_hash, lagging, *values = row
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
        return Record(
            id=row_id,
            rule=rule.name,
            fields=fields,
            location=location,
            state=state,
            revision=revision,
            config_version=config_version,
            attributes=_decode_attributes(rule, stored, location),
            content_hash=content_hash,
            lagging=tuple(json.loads(lagging)),
        )


def _column(key: str) -> str:
    # Key names are letters, digits and '_', so quoting is only a guard against SQL keywords.
    return f'"key_{key}"'


def _encode_attributes(rule: Rule, attributes: Mapping[str, Any]) -> str:
    for name, value in attributes.items():
        try:
            json.dumps(value, default=json_default, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise InvalidValueError(f"rule {rule.name!r}: attribute {name!r} cannot be stored: {exc}") from None
    return canonical_json(attributes)


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
