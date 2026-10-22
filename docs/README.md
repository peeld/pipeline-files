# Entity Layout & Storage Abstraction: Design Plan

**Status:** Draft. Phases 1 to 6 are implemented. **Last updated:** 2026-10-21.

This plan defines a small, storage-neutral layer that lets tools ask for things by name and fields instead of by path, and keeps those things consistent across a filesystem, a database and cloud storage.

## Contents

1. [Purpose and scope](01-purpose-and-scope.md)
2. [Core concepts](02-core-concepts.md)
3. [Layered architecture](03-layered-architecture.md)
4. [Configuration model](04-configuration-model.md)
5. [Query model](05-query-model.md)
6. [Authority and links](06-authority-and-links.md)
7. [Write lifecycle and failure handling](07-write-lifecycle-and-failure-handling.md)
8. [Offline operation and holding space](08-offline-operation-and-holding-space.md)
9. [Conflict resolution](09-conflict-resolution.md)
10. [Worked examples](10-worked-examples.md)
11. [Risks and implementation considerations](11-risks-and-implementation-considerations.md)
12. [Build order and verification](12-build-order-and-verification.md)
13. [Implementation plan](13-implementation-plan.md)

## Decision records

Settled decisions are recorded one per file in [decisions/](decisions/README.md). Treat them as constraints when implementing. Everything else in the numbered documents is a proposal that is open to comment.

- [0001: One authority per entity type, with active and passive links](decisions/0001-one-authority-per-entity-type.md)
- [0002: Per-element holding space with uuid identity](decisions/0002-per-element-holding-space.md)
- [0003: Clashes resolve by version up, suffix or fail](decisions/0003-clash-resolution-outcomes.md)
- [0004: Operations are optional and fail when not implemented](decisions/0004-operations-optional-and-fail-if-missing.md)
- [0005: Attributes are typed and not validated on use](decisions/0005-attributes-typed-not-validated.md)
- [0006: Python reference implementation, language-neutral configuration](decisions/0006-python-reference-implementation.md)
- [0007: YAML configuration in named sections, checked by a JSON Schema](decisions/0007-yaml-config-with-json-schema.md)
- [0008: Template syntax, and parsing that refuses ambiguity](decisions/0008-template-syntax-and-strict-parsing.md)
- [0009: Locations are URIs of backend, logical root and relative path](decisions/0009-location-uris.md)
- [0010: Filesystem queries are strict and fail loudly](decisions/0010-filesystem-queries-are-strict.md)
- [0011: SQLite keeps one entities table, and rows borrow a template for their location](decisions/0011-sqlite-table-layout.md)
- [0012: Links are named per rule, with a role and settings, and bound to backends at run time](decisions/0012-link-configuration.md)
- [0013: Records carry a state, every step is logged before it acts, and recovery replays the log](decisions/0013-records-operation-log-and-write-steps.md)
- [0014: Sidecars are hidden JSON files, stamped with revision and hash](decisions/0014-json-sidecars.md)
- [0015: Held work merges on its own unless the rule asks for confirmation, and old work always waits for a person](decisions/0015-merge-trigger-and-age-limit.md)
- [0016: Held elements are folders with a manifest, claims are atomic creates, and a merge is a write under the element's uuid](decisions/0016-holding-elements-claims-and-merge.md)
- [0017: A clash rule changes a key the rule names, the link that finds the clash decides, and the requested key is kept](decisions/0017-clash-keys-and-the-requested-key.md)
- [0018: Migration is a site's script that keeps identity, history and links, with the old authority offline](decisions/0018-migration-keeps-identity-history-and-links.md)
- [0019: A passive link runs on one call, by link or event name, and reports each link's result](decisions/0019-passive-links-run-on-one-call.md)

## Notes for implementers and agents

- The design is deliberately generic. The five worked examples in [Worked examples](10-worked-examples.md) are illustrations from different fields, not requirements.
- Items listed under "Left to the implementation" in [Risks and implementation considerations](11-risks-and-implementation-considerations.md) are intentionally undecided. Decide them when the relevant phase in [Build order and verification](12-build-order-and-verification.md) is built.
- Diagrams are Mermaid blocks, so their source is plain text and renders on GitHub and GitLab.
- The code lives in `src/entitylayout/`, and the worked examples are test fixtures in `tests/fixtures/`. The [implementation plan](13-implementation-plan.md) maps phases to code and tracks what is done. The next tasks are listed in `TODO.md` at the repository root.

## Giving feedback

Comments are welcome. Please open an issue or a pull request that names the document and section it refers to. One topic per issue keeps discussion easy to follow. Questions that are listed as open in document 11 are good places to start.
