# Decision records

Settled decisions, one per file. Treat them as constraints when implementing.

- [0001: One authority per entity type, with active and passive links](0001-one-authority-per-entity-type.md)
- [0002: Per-element holding space with uuid identity](0002-per-element-holding-space.md)
- [0003: Clashes resolve by version up, suffix or fail](0003-clash-resolution-outcomes.md)
- [0004: Operations are optional and fail when not implemented](0004-operations-optional-and-fail-if-missing.md)
- [0005: Attributes are typed and not validated on use](0005-attributes-typed-not-validated.md)
- [0006: Python reference implementation, language-neutral configuration](0006-python-reference-implementation.md)
- [0007: YAML configuration in named sections, checked by a JSON Schema](0007-yaml-config-with-json-schema.md)
- [0008: Template syntax, and parsing that refuses ambiguity](0008-template-syntax-and-strict-parsing.md)
- [0009: Locations are URIs of backend, logical root and relative path](0009-location-uris.md)
- [0010: Filesystem queries are strict and fail loudly](0010-filesystem-queries-are-strict.md)
- [0011: SQLite keeps one entities table, and rows borrow a template for their location](0011-sqlite-table-layout.md)
- [0012: Links are named per rule, with a role and settings, and bound to backends at run time](0012-link-configuration.md)
- [0013: Records carry a state, every step is logged before it acts, and recovery replays the log](0013-records-operation-log-and-write-steps.md)
- [0014: Sidecars are hidden JSON files, stamped with revision and hash](0014-json-sidecars.md)
- [0015: Held work merges on its own unless the rule asks for confirmation, and old work always waits for a person](0015-merge-trigger-and-age-limit.md)
- [0016: Held elements are folders with a manifest, claims are atomic creates, and a merge is a write under the element's uuid](0016-holding-elements-claims-and-merge.md)
- [0017: A clash rule changes a key the rule names, the link that finds the clash decides, and the requested key is kept](0017-clash-keys-and-the-requested-key.md)
- [0018: Migration is a site's script that keeps identity, history and links, with the old authority offline](0018-migration-keeps-identity-history-and-links.md)
- [0019: A passive link runs on one call, by link or event name, and reports each link's result](0019-passive-links-run-on-one-call.md)

[Index](../README.md)
