# 0015: Held work merges on its own unless the rule asks for confirmation, and old work always waits for a person

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Risks and implementation considerations](../11-risks-and-implementation-considerations.md) left two holding questions to phase 5. Should merge run on its own when the authority returns, or wait for a person? And how long may a held element wait before someone must look at it again? The document suggested a per-rule setting for the first.

Most held work is routine, such as a render made on a train or a run on a cluster with no route to the database. Making a person confirm each one would turn holding into a chore. But some entity types matter enough that a person should see every merge. And work held for weeks was made against an authority that has moved on since.

## Decision

- **Two settings on the authority link**, beside `offline: hold`. They are set per rule, in the links section, like the other link settings ([decision 0012](0012-link-configuration.md)).

| Setting | Values | Default | Meaning |
| --- | --- | --- | --- |
| `merge` | `auto` or `confirm` | `auto` | With `auto`, a merge takes held work without asking. With `confirm`, each element waits until a person confirms it |
| `max_age` | A whole number of days, hours or minutes, such as `7d`, `36h` or `90m` | No limit | Held work older than this waits for a person, even under `auto` |

- **Both need `offline: hold`.** Setting either on an authority with another offline policy is refused when the configuration loads.
- **Waiting is an outcome, not a failure.** An element that needs confirming is reported as `awaiting_confirmation`, with the reason. It is never merged, changed or deleted until a person confirms it by its ID.
- **The library does not run in the background.** `merge` means "when a tool calls `Engine.merge()`". A tool calls it when it starts, as it calls `recover()`, or whenever it sees the authority come back.
- **Age is measured from when the element was held**, in UTC. Merge order never depends on clocks. Only this check does, and a clock that is a little off only moves the moment a person is asked.

```yaml
links:
  shot:
    tracking: {role: authority, offline: hold, merge: auto, max_age: 7d}
    files: {role: active}
```

## Consequences

- Routine offline work merges with no one involved. A rule that needs care, such as approved deliverables, sets `merge: confirm`.
- Old work cannot slip in unseen. A person sees it first, and can confirm it, give it new fields, or discard it.
- Nothing is ever deleted for being old.

Details: [Offline operation and holding space](../08-offline-operation-and-holding-space.md).
