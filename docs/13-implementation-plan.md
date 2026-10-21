# Implementation plan

This turns the [build order](12-build-order-and-verification.md) into concrete steps, and records where the work stands. Phases 1 and 2 are built and their gates pass. Phase 3 is next. Each later phase starts only after the gate before it passes.

## Choices made before code

| Question | Choice | Recorded in |
| --- | --- | --- |
| Language | Python 3.10 or later, package `entitylayout` | [0006](decisions/0006-python-reference-implementation.md) |
| Configuration format | YAML in named sections, one file or many, with a JSON Schema | [0007](decisions/0007-yaml-config-with-json-schema.md) |
| Template syntax | `{key}` placeholders, `[ ... ]` optional groups, ambiguous names refused | [0008](decisions/0008-template-syntax-and-strict-parsing.md) |
| Location format | `<backend>://<root>/<path>` | [0009](decisions/0009-location-uris.md) |
| Filesystem query behavior | Skip names that do not fit, fail on names that fit two ways | [0010](decisions/0010-filesystem-queries-are-strict.md) |
| Key defaults | Fixed values only. "Latest" is a query filter | [Configuration model](04-configuration-model.md) |
| Embedded database | SQLite, from the Python standard library | To decide in phase 3 |
| Filesystem attributes | A JSON sidecar with attributes, internal ID, config version, revision and hash | To decide in phase 4 |

## Source layout

| Path | Contents |
| --- | --- |
| `src/entitylayout/keys.py` | Typed keys: checking values, writing them into names and reading them back |
| `src/entitylayout/template.py` | Template syntax, formatting and parsing in both directions |
| `src/entitylayout/roots.py` | Logical roots and their real location per host and operating system |
| `src/entitylayout/layout.py` | Loading configuration, rule inheritance, and resolving in both directions |
| `src/entitylayout/location.py` | Location URIs |
| `src/entitylayout/check.py` | The validation pass for required directories |
| `src/entitylayout/backends/base.py` | The backend interface and its published operations |
| `src/entitylayout/backends/filesystem.py` | The filesystem backend: a level-by-level walk with pruning |
| `src/entitylayout/entity.py` | The entities a query returns |
| `src/entitylayout/query.py` | Queries and composable filters |
| `src/entitylayout/cli.py` | `entitylayout CONFIG check`, `locate`, `parse` and `query` |
| `schema/layout.schema.json` | The configuration's shape, for any language |
| `tests/fixtures/` | One configuration per worked example: visual effects, data science, industrial design, office and lab |

Later phases add more backends, and `engine/` and `holding/` beside these.

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

## Phase 3: Second backend and metadata (next)

- [ ] Decide the table layout and record it as decision 0011. See the design notes below.
- [ ] An SQLite backend in `src/entitylayout/backends/sqlite.py` with key columns and typed attributes, which compiles queries to a WHERE clause with bound parameters.
- [ ] A `create` operation on the SQLite backend, so tests and import tools can load entities. The filesystem backend leaves it unimplemented until the write flow in phase 4.
- [ ] Attribute filters on queries: equality to start with, on backends that declare they support them.
- [ ] Capability flags, such as ad-hoc attribute queries and atomic multi-record updates, published beside the supported operations.
- [ ] A place for the optional attribute validation layer ([decision 0005](decisions/0005-attributes-typed-not-validated.md)).
- [ ] **Gate:** one query suite runs on both backends, loaded from the same fixtures, with identical results.

**Design notes for phase 3**

- **Table layout.** Keys are defined once and reused across rules, so the recommended layout is one `entities` table with a `rule` column, one typed column per key (null where a rule does not use it), an `attributes` JSON column, and the formatted location path. Make `(rule, location)` unique rather than the key columns, because SQLite treats nulls as distinct in unique indexes and optional keys can be null. The round-trip gate already guarantees one location per set of fields. The alternative, one table per rule, gives tighter typing but needs a schema change for every new rule.
- **Column types.** `int` keys become INTEGER, `string` keys TEXT, and `date` keys ISO-8601 TEXT, so they still sort and compare correctly.
- **Ready for phase 4.** Reserve columns for the internal ID (a uuid) and the config version now, even if phase 3 only fills them on create.
- **Gate shape.** Reuse the strategies in `tests/strategies.py` and the tree builder in `tests/test_query_gate.py`. Generate entities once, write them to a directory tree and into SQLite, run the same random partial queries on both, and require identical fields and locations, in the same order.
- **Location for database rows.** A row's location is the rule's template for that backend, formatted from its fields. So a rule needs a template for the database backend's name, or the backend reuses the `fs` template. Decide which, and record it with the table layout.

## Known gaps and follow-ups

These came up while building phases 1 and 2. None blocks phase 3.

- **Windows and macOS are untested.** The test workflow covers them, but it has not run yet, because nothing has been pushed. The likely trouble spots are case-insensitive names and path length.
- **A query cannot ask for an optional key to be absent.** Leaving a key out, or passing None, means "anything". If people need "no variant", it needs its own marker.
- **`newest` groups by every other key by default.** On a rule with a frame key, `newest("version")` keeps the newest version of each frame, not the newest version as a whole. Use `within=` to choose the grouping. The `--newest` option on the command line has no way to set it yet.
- **Finding keys that could contain `/` is a heuristic.** The filesystem backend tests a few sample values and looks for `/` in the pattern. A pattern that allows `/` only in unusual positions could slip through.
- **A permission error during a walk is not handled.** It currently propagates and stops the query. Decide whether to skip and report it instead.
- **Templates cannot contain literal `{`, `}`, `[` or `]`.** Add an escape syntax if a real layout needs one.
- **The property tests take about 45 seconds.** Nearly all of that is Hypothesis generating values from the wide default string pattern, not the library.

## Phase 4: Authority, active links, rollback

- [ ] Link configuration per rule: role, order, triggers, rollback, clash rule and offline policy. The `links` section is already accepted and kept unread until then.
- [ ] Records with an internal ID, state, revision and content hash, and an operation log written in the same transaction.
- [ ] The write flow: reserve, realize active links in order, then commit, roll back what was created, or mark out of sync.
- [ ] Sidecars stamped with revision and hash, and recovery from the operation log.
- [ ] **Gate:** injected failures at every step leave only the declared record states.

## Phase 5: Holding and merge

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
```

---

Previous: [Build order and verification](12-build-order-and-verification.md) | [Index](README.md)
