# 0003: Clashes resolve by version up, suffix or fail

**Status:** Accepted. **Date:** 2026-10-21.

## Context

Two entities can claim the same key, an edit can be based on an out-of-date revision, or a file can exist with different content. The system has to settle these without interpreting file bytes.

## Decision

Every conflict is settled by exactly one of three outcomes: version up, add a number suffix, or fail the operation. There is no content merging.

- The rule that applies is configured per link.
- Replicated records carry the authority revision they derive from and a hash of what was written, so stale or hand-edited records can be detected.
- A hand-edited sidecar is treated as a proposed edit against its recorded base revision and goes through the same resolution.
- The originally requested key is stored beside the final key.

## Consequences

- A suffix or version change alters an entity's label but not its identity, so references by internal ID survive.
- Clash avoidance, such as provisional machine-tagged suffixes or pre-assigned version blocks, is preferred where possible because it is cheaper than resolving after the fact.

Details: [Conflict resolution](../09-conflict-resolution.md).
