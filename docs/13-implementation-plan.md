# Implementation plan

This turns the [build order](12-build-order-and-verification.md) into concrete steps, and records where the work stands. Phase 1 is built and its gate passes. Each later phase starts only after the gate before it passes.

## Choices made before code

| Question | Choice | Recorded in |
| --- | --- | --- |
| Language | Python 3.10 or later, package `entitylayout` | [0006](decisions/0006-python-reference-implementation.md) |
| Configuration format | YAML in named sections, one file or many, with a JSON Schema | [0007](decisions/0007-yaml-config-with-json-schema.md) |
| Template syntax | `{key}` placeholders, `[ ... ]` optional groups, ambiguous names refused | [0008](decisions/0008-template-syntax-and-strict-parsing.md) |
| Location format | `<backend>://<root>/<path>` | [0009](decisions/0009-location-uris.md) |
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
| `src/entitylayout/cli.py` | `entitylayout CONFIG check`, `locate` and `parse` |
| `schema/layout.schema.json` | The configuration's shape, for any language |
| `tests/fixtures/` | One configuration per worked example: visual effects, data science, industrial design, office and lab |

Later phases add `backends/`, `query/`, `engine/` and `holding/` beside these.

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

## Phase 2: Filesystem backend and query

- [ ] A backend interface that publishes the operations it supports and fails on any other ([decision 0004](decisions/0004-operations-optional-and-fail-if-missing.md)).
- [ ] A filesystem backend that walks one level at a time. It uses each template's literal text and known keys to prune, then parses every candidate strictly.
- [ ] A query of a rule plus partial fields that returns entities, with a location only on request and a provisional flag that stays false until phase 5.
- [ ] Composable filters: newest version, sort, group, and collapse a numbered sequence.
- [ ] **Gate:** partial-field queries return exactly the expected entities from real directory trees built from each fixture.

## Phase 3: Second backend and metadata

- [ ] An SQLite backend with key columns and typed attributes, which compiles queries to a WHERE clause.
- [ ] Capability flags, such as ad-hoc attribute queries and atomic multi-record updates.
- [ ] A place for the optional attribute validation layer ([decision 0005](decisions/0005-attributes-typed-not-validated.md)).
- [ ] **Gate:** one query suite runs on both backends, loaded from the same fixtures, with identical results.

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
```

---

Previous: [Build order and verification](12-build-order-and-verification.md) | [Index](README.md)
