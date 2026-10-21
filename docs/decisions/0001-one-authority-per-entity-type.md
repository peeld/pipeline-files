# 0001: One authority per entity type, with active and passive links

**Status:** Accepted. **Date:** 2026-10-21.

## Context

An entity can exist in several places at once, such as a database, a filesystem and cloud storage. Without a rule for which copy is the truth, the copies drift apart and nobody can say which one is right.

## Decision

Each entity type names exactly one authority. Every other place the entity exists is a link, either active or passive.

- **Authority.** Its record is the truth. It is always changed first on a write, and if it fails the whole operation stops.
- **Active link.** Updated as part of the same write, in a declared order. If an active link fails, the write is rolled back when rollback is available, which is the default. Otherwise the link is marked out of sync and retried.
- **Passive link.** Not updated automatically. It changes only on an explicit call or when a later triggering event fires.
- When the authority is unreachable, work follows the entity type's offline policy (see decision 0002).

## Consequences

- Active and passive links are the same mechanism (an action bound to an event) with different timing and failure policies.
- The authority is a configuration choice per entity type, so a migration tool is needed to change it.
- A filesystem authority is possible but only eventually consistent for links, because outside changes are found by scanning or watching.

Details: [Authority and links](../06-authority-and-links.md), [Write lifecycle and failure handling](../07-write-lifecycle-and-failure-handling.md).
