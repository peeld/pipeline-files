# Implementation plan

This turns the [build order](12-build-order-and-verification.md) into concrete steps, and records where the work stands. Phases 1 to 4 are built and their gates pass. Phase 5 is next. Each later phase starts only after the gate before it passes.

## Choices made before code

| Question | Choice | Recorded in |
| --- | --- | --- |
| Language | Python 3.10 or later, package `entitylayout` | [0006](decisions/0006-python-reference-implementation.md) |
| Configuration format | YAML in named sections, one file or many, with a JSON Schema | [0007](decisions/0007-yaml-config-with-json-schema.md) |
| Template syntax | `{key}` placeholders, `[ ... ]` optional groups, ambiguous names refused | [0008](decisions/0008-template-syntax-and-strict-parsing.md) |
| Location format | `<backend>://<root>/<path>` | [0009](decisions/0009-location-uris.md) |
| Filesystem query behavior | Skip names that do not fit, fail on names that fit two ways | [0010](decisions/0010-filesystem-queries-are-strict.md) |
| Key defaults | Fixed values only. "Latest" is a query filter | [Configuration model](04-configuration-model.md) |
| Embedded database | SQLite, from the Python standard library, one `entities` table | [0011](decisions/0011-sqlite-table-layout.md) |
| Link configuration | Named links per rule with a role and settings, bound to backends at run time | [0012](decisions/0012-link-configuration.md) |
| Write flow | Record states, a log written before each step acts, named steps, recovery by replay | [0013](decisions/0013-records-operation-log-and-write-steps.md) |
| Filesystem attributes | A hidden JSON sidecar with attributes, internal ID, config version, revision and hash | [0014](decisions/0014-json-sidecars.md) |

## Source layout

| Path | Contents |
| --- | --- |
| `src/entitylayout/keys.py` | Typed keys: checking values, writing them into names and reading them back |
| `src/entitylayout/template.py` | Template syntax, formatting and parsing in both directions |
| `src/entitylayout/roots.py` | Logical roots and their real location per host and operating system |
| `src/entitylayout/layout.py` | Loading configuration, rule inheritance, and resolving in both directions |
| `src/entitylayout/location.py` | Location URIs |
| `src/entitylayout/links.py` | The links section: one authority, ordered active links and passive links per rule |
| `src/entitylayout/records.py` | Authority records and their states, the operation log entries, content hashes and sidecars |
| `src/entitylayout/engine.py` | The write flow: reserve, realize active links in order, settle; rollback and recovery |
| `src/entitylayout/check.py` | The validation pass for required directories |
| `src/entitylayout/backends/base.py` | The backend interface and its published operations |
| `src/entitylayout/backends/filesystem.py` | The filesystem backend: a level-by-level walk with pruning, and an idempotent link step with undo |
| `src/entitylayout/backends/sqlite.py` | The SQLite backend: one table of records, queries compiled to SQL, rows checked on read, the operation log |
| `src/entitylayout/validation.py` | The optional attribute validation layer |
| `src/entitylayout/entity.py` | The entities a query returns |
| `src/entitylayout/query.py` | Queries and composable filters |
| `src/entitylayout/cli.py` | `entitylayout CONFIG check`, `locate`, `parse` and `query`, on the filesystem or a database |
| `schema/layout.schema.json` | The configuration's shape, for any language |
| `tests/fixtures/` | One configuration per worked example: visual effects, data science, industrial design, office and lab |

Later phases add more backends, and `holding/` beside these.

## Phase 1: Schema and rules (done)

- [x] Keys with type, choices, pattern, format, padding, date format, default and required.
- [x] Strict, canonical key text: a value is accepted only if writing it again gives the same text.
- [x] Rules with ordered keys, parents, a root, a template per backend, optional groups and typed attributes.
- [x] Roots resolved by host pattern, then operating system, then default.
- [x] Configuration loading from one file or a directory, with a required version and errors that name the rule and key at fault.
- [x] Parsing that tries every split and refuses an ambiguous name.
- [x] Locations as URIs, real paths per machine, and real paths back to locations.
- [x] A validation pass that reports missing roots and never creates anything.
- [x] A JSON Schema for the configuration, checked against every fixture.
- [x] A command line for checking, locating and parsing.
- [x] **Gate:** a property test generates fields for every rule in all five fixtures, from each key's own definition. It checks that fields go to a location and back unchanged, and the same through a URI and a real path. A separate test shows the gate fails on a loosely constrained layout.

## Phase 2: Filesystem backend and query (done)

- [x] A backend interface that publishes the operations it supports and fails on any other ([decision 0004](decisions/0004-operations-optional-and-fail-if-missing.md)). The supported list is worked out from which operations a backend overrides, so it cannot drift from the code.
- [x] A filesystem backend that walks one level at a time. A level whose keys are all known is checked directly; any other is listed once per query and every name parsed strictly ([decision 0010](decisions/0010-filesystem-queries-are-strict.md)).
- [x] A query of a rule plus partial fields that returns entities with a location URI and a provisional flag, which stays false until phase 5.
- [x] Composable filters: newest, sort, where, group, and collapse a numbered sequence into ranges.
- [x] `exists` for a full set of fields, and a `query` command on the command line.
- [x] **Gate:** for every rule in all five fixtures, a property test creates a random set of entities on disk, runs a random partial-field query, and checks the results are exactly the entities that match. Other tests check that known keys prune the walk, that junk names are skipped, and that ambiguous names fail.

## Phase 3: Second backend and metadata (done)

- [x] The table layout, recorded as [decision 0011](decisions/0011-sqlite-table-layout.md): one `entities` table with a `rule` column, a typed column per key, an `attributes` JSON column, and `(rule, location)` unique. The internal ID and config version columns are reserved for phase 4 and filled on create.
- [x] Rows borrow a template for their location, `fs` by default, so the database and the filesystem give an entity the same location URI.
- [x] An SQLite backend in `src/entitylayout/backends/sqlite.py` that compiles queries to a WHERE clause with bound parameters, and checks every row it reads against its rule.
- [x] A `create` operation on the SQLite backend, and `transaction()` to group writes. The filesystem backend leaves `create` unimplemented. Phase 4 gives it `realize` and `undo` as a link step instead.
- [x] Attribute filters on queries: equality to a string, number, boolean or date, on backends with the `attribute_queries` capability.
- [x] Capability flags, `attribute_queries` and `atomic_updates`, declared beside the supported operations. An unknown capability name fails when the class is defined.
- [x] An optional validator that every write calls first, and `TypedAttributes` in `src/entitylayout/validation.py`, which checks declared types ([decision 0005](decisions/0005-attributes-typed-not-validated.md)).
- [x] `query --db PATH` and `--attr NAME=VALUE` on the command line.
- [x] **Gate:** for every rule in all five fixtures, a property test generates entities once, writes them to a directory tree and into SQLite, runs the same random partial-field query on both, and requires identical rules, fields and locations in the same order. It also runs the same filter chain on both. A second property test checks attribute filters, on declared and undeclared attributes of every scalar type, against filtering the stored attributes directly.

## Known gaps and follow-ups

These came up while building phases 1 to 4. None blocks phase 5.

- **Windows and macOS are untested.** The test workflow covers them. It first ran when `main` was pushed on 2026-10-21, and its results have not been checked yet. The likely trouble spots are case-insensitive names and path length.
- **A query cannot ask for an optional key to be absent.** Leaving a key out, or passing None, means "anything". If people need "no variant", it needs its own marker.
- **`newest` groups by every other key by default.** On a rule with a frame key, `newest("version")` keeps the newest version of each frame, not the newest version as a whole. Use `within=` to choose the grouping. The `--newest` option on the command line has no way to set it yet.
- **Finding keys that could contain `/` is a heuristic.** The filesystem backend tests a few sample values and looks for `/` in the pattern. A pattern that allows `/` only in unusual positions could slip through.
- **A permission error during a walk is not handled.** It currently propagates and stops the query. Decide whether to skip and report it instead.
- **Templates cannot contain literal `{`, `}`, `[` or `]`.** Add an escape syntax if a real layout needs one.
- **The property tests take about 110 seconds.** Nearly all of that is Hypothesis generating values from the wide default string pattern, not the library. The phase 4 gate adds about 20 seconds.
- **SQLite cannot hold an `int` key beyond 64 bits.** A pattern such as `[0-9]+` allows one on the filesystem. Creating or querying one in SQLite fails loudly. If a layout needs such keys, store them as TEXT with a sortable encoding.
- **Parent rows are not implied in a database.** On the filesystem, a media directory implies its shot directory. In SQLite, the shot exists only if it was created. An import tool that loads a tree must create parent rows too.
- **Attribute filters test equality only.** Ranges, "absent" and container values need a `where` filter for now. The JSON column is not indexed, so attribute filters scan a rule's rows.
- **Recovery is not safe to run concurrently.** Two processes recovering the same database could both undo or realize one record. Run recovery from one place until claim markers exist (phase 5).
- **A lost file content leaves a record out of sync.** The authority keeps a file's hash, not its bytes. If a crash comes before the file is written and rollback is off, only `retry()` with the content can finish it.
- **There are no updates or deletes yet.** Records start and stay at revision 1. Overwrites, renames and deletes cannot be undone, so they will fall back to out of sync with a retry, as the write lifecycle describes.
- **The command line cannot write.** There is no `create` or `recover` command yet.
- **Writes use one temporary file and a rename.** A file that appears at the target between the check and the rename is replaced. Closing that gap needs a create-if-absent primitive per platform.
- **The database schema only grows.** Opening a database adds columns for new keys, but never retypes or drops one. Changing a key's type needs a migration (phase 6).

## Phase 4: Authority, active links, rollback (done)

- [x] Link configuration per rule, recorded as [decision 0012](decisions/0012-link-configuration.md): named links with a role, order, triggers, rollback, clash rule and offline policy, in the JSON Schema and read in `src/entitylayout/links.py`. A rule without links uses its parent's. Every fixture now declares its links.
- [x] Records with an internal ID, state, revision, content hash and lagging links. SQLite schema version 2 adds them with an `operations` table, and upgrades a version 1 database when it is opened. Each change of state and its log entry commit in one transaction.
- [x] Normal queries hide pending and failed records. Out of sync entities carry their lagging links, and entities from SQLite carry their internal ID. A failed record no longer holds its location.
- [x] The write flow in `src/entitylayout/engine.py`, as named steps a test can fail: reserve, realize the active links in order, then commit, roll back what was made, or mark out of sync ([decision 0013](decisions/0013-records-operation-log-and-write-steps.md)).
- [x] The filesystem backend is an active link: `realize` makes missing directories, then the sidecar, then the file, logging each item first. `undo` removes only logged items that are unchanged, and only empty directories.
- [x] Sidecars as hidden JSON, stamped with revision and hash, so stale and hand-edited ones are detected ([decision 0014](decisions/0014-json-sidecars.md)). `recover()` replays the operation log, and `retry()` catches up an out of sync record.
- [x] The offline policies `fail` and `read_only`. Under `read_only`, writes fail with `ReadOnlyError` and queries fall back to an active link.
- [x] **Gate:** for every rule in all five fixtures, with rollback on and off, a property test generates an entity (a directory or a file) and committed neighbours that share its path. It fails each step of the write in turn, crashes at each step, and adds a second failure or crash at each step the first one leads to. After every run and after recovery, the record must be in a declared state that the queries and the disk agree with, and the neighbours must be untouched. A single failure must give the exact state that decision 0013 declares.

**Design notes for phase 5**

- **Holding needs the engine's checks relaxed.** The engine refuses `hold`, `version_up` and `suffix` when it is built. Phase 5 implements them and removes those refusals.
- **Merge is a write.** A held element merges through the same flow: reserve under its own uuid, so a second merge finds the ID and stops, then realize and commit. `reserve` will need to accept a given internal ID, and refuse a different one at the same key.
- **The requested key is kept.** Store it beside the final key when a clash rule changes it. That is a new column, so schema version 3.
- **Hand-edited sidecars become proposals.** `Sidecar.edited` and `Sidecar.stale()` already detect them. Phase 5 turns them into edits against the recorded base revision.
- **Claim markers.** Recovery assumes no concurrent writer. Holding's claim markers are the place to make recovery safe to run from two machines.

## Phase 5: Holding and merge## Phase 5: Holding and merge

- [ ] Per-element holding with a manifest, an overlay for the owner, claim markers and idempotent merge by internal ID.
- [ ] Merge in dependency order, with clash rules applied and the requested key kept.
- [ ] Decide the holding age limit and the merge trigger ([open questions](11-risks-and-implementation-considerations.md)).
- [ ] **Gate:** replayed offline sessions with injected clashes resolve exactly as configured.

## Phase 6: Passive links and migration

- [ ] Event triggers for passive links, and an object-storage backend.
- [ ] Decide whether migration is a script or a supported tool, then build it.
- [ ] **Gate:** a migrated entity type keeps identity, history and every link.

## Working on the code

```sh
python -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest
.venv/bin/entitylayout tests/fixtures/vfx locate media project=alpha sequence=ABC shot=40 version=3 camera=main
.venv/bin/entitylayout path/to/layout query media shot=40 --newest version
.venv/bin/entitylayout path/to/layout query media shot=40 --db entities.db --attr status=approved
```

---

Previous: [Build order and verification](12-build-order-and-verification.md) | [Index](README.md)
