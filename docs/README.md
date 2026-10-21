# Entity Layout & Storage Abstraction: Design Plan

**Status:** Draft. **Last updated:** 2026-10-21.

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

## Decision records

Settled decisions are recorded one per file in [decisions/](decisions/README.md). Treat them as constraints when implementing. Everything else in the numbered documents is a proposal that is open to comment.

- [0001: One authority per entity type, with active and passive links](decisions/0001-one-authority-per-entity-type.md)
- [0002: Per-element holding space with uuid identity](decisions/0002-per-element-holding-space.md)
- [0003: Clashes resolve by version up, suffix or fail](decisions/0003-clash-resolution-outcomes.md)
- [0004: Operations are optional and fail when not implemented](decisions/0004-operations-optional-and-fail-if-missing.md)
- [0005: Attributes are typed and not validated on use](decisions/0005-attributes-typed-not-validated.md)

## Notes for implementers and agents

- The design is deliberately generic. The five worked examples in [Worked examples](10-worked-examples.md) are illustrations from different fields, not requirements.
- Items listed under "Left to the implementation" in [Risks and implementation considerations](11-risks-and-implementation-considerations.md) are intentionally undecided. Decide them when the relevant phase in [Build order and verification](12-build-order-and-verification.md) is built.
- Diagrams are Mermaid blocks, so their source is plain text and renders on GitHub and GitLab.

## Giving feedback

Comments are welcome. Please open an issue or a pull request that names the document and section it refers to. One topic per issue keeps discussion easy to follow. Questions that are listed as open in document 11 are good places to start.
