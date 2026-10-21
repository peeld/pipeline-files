# 0011: SQLite keeps one entities table, and rows borrow a template for their location

**Status:** Accepted. **Date:** 2026-10-21.

## Context

Phase 3 adds an embedded database as the second backend. It needs a table layout, and each row needs a location that means the same thing as a location from any other backend.

Keys are defined once and reused across rules, so a column per key can be shared by every rule that uses the key. Rules can be added at any time, and should not need a schema change each time.

## Decision

- **One table.** All entities live in one `entities` table. It has a `rule` column, one typed column per key (null where a rule does not use the key), an `attributes` JSON column and the formatted location path.
- **Column types.** `int` keys are INTEGER, `string` keys are TEXT, and `date` keys are ISO-8601 TEXT, so they still sort and compare correctly. Key columns are named `key_<name>`, so a key can never clash with a fixed column.
- **64-bit integers.** An `int` key value outside the signed 64-bit range cannot be stored. Creating or querying one raises an error that names the key, even though a key pattern such as `[0-9]+` allows it on the filesystem.
- **Uniqueness.** `(rule, location)` is unique, not the key columns, because SQLite treats nulls as distinct in a unique index and optional keys can be null. The round-trip gate already guarantees one location per set of fields.
- **Reserved for phase 4.** Each row has an internal ID (a uuid, the primary key) and the config version that created it. Phase 3 fills both on create.
- **Locations borrow a template.** The backend is built for one template name, `fs` by default, and a row's location is that rule's template formatted from the row's fields. Following [decision 0009](0009-location-uris.md), the URI names the template, so a row read through the `fs` template has an `fs://` location, identical to the one the filesystem backend returns. A layout that wants its own database paths adds a template under another name and builds the backend with it.
- **One template per database.** The database records the template name it was created for, and opening it with a different one fails.
- **The schema follows the layout.** Opening a database adds a column for any new key. Columns are never dropped or retyped.
- **Rows are checked on read.** Every row read back is formatted again from its fields. A row whose stored location or values no longer fit the rule raises an error that names the row.

## Consequences

- A new rule needs no schema change, and a new key is one added column.
- Typing is per key, not per rule, which is enough because a key has one type everywhere.
- The filesystem and the database return identical entities for identical data, so the phase 3 gate can compare them directly.
- A rule with no template under the backend's name cannot be stored in that database.
- On the filesystem, creating a child entity also creates its parent's directory, so the parent exists too. A database row exists only if it was created. Tools that load a database from a tree must create parent rows themselves.

Details: [Query model](../05-query-model.md).
