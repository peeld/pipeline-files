# 0016: Held elements are folders with a manifest, claims are atomic creates, and a merge is a write under the element's uuid

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Decision 0002](0002-per-element-holding-space.md) settled that held work is kept one element at a time, named by a uuid that becomes its internal ID. Phase 5 has to decide what an element holds on disk, how two machines avoid merging one element, how a merge reuses the write flow of [decision 0013](0013-records-operation-log-and-write-steps.md), and what each merge can end in.

## Decision

**The holding area** is a directory that a tool passes to the engine. An engine whose rules use `offline: hold` is refused when it is built without one. Each element is a folder named by its uuid.

| File | Holds |
| --- | --- |
| `manifest.json` | Format and version, the uuid, the rule, the requested fields with defaults filled in, the attributes, the held parent, the owner, the owner's sequence number, the time held, the config version and the content hash |
| `content` | The file's bytes, for a file entity |
| `claim.json` | Who is merging the element now |

- **Written whole.** An element is written in a hidden folder and renamed into place. A merged one is renamed to a hidden folder, then removed. A name starting with a dot is never an element.
- **The manifest is the sidecar.** It already holds the identity and attributes a sidecar would, so a held element has no second copy of them. A sidecar is written when the element merges.
- **One owner per element.** The owner is a name for the machine or user, the host name by default. The owner's queries show its own elements overlaid on the authority's answer, flagged provisional. Other owners do not see them. A merge takes the owner's elements, and another owner's only when asked to adopt them.
- **No duplicates.** An owner cannot hold two elements of one rule with the same fields.
- **Parents by ID.** When an element is held, its nearest ancestor that the owner also holds is recorded by uuid. The element merges after that ancestor, and its keys are taken from the ancestor's final record.

**Claims** are made by an atomic create. They never use file locks.

- An element's claim is `claim.json`, made with exclusive create. An authority record's claim is a row in the authority's `claims` table, whose primary key makes the insert atomic.
- A claim names its claimant. A claimant that holds a claim may take it again, so a machine that restarts under the same name finishes its own work. By default each engine has a unique name.
- Claims do not expire. A claim left by a process that died is released by a person, with `Holding.release` or `Engine.release`.
- `recover()` claims each record first, and skips records another claimant holds. Two recoveries can run against one database.

**A merge is a write.** Each element merges through the same steps as a create, in owner and sequence order, with parents first.

- **By internal ID.** The record is reserved under the element's uuid. If the authority already has a committed record with that ID, the merge was done before, and only the element is removed. A pending or out of sync record is finished from the log with the held content. A failed record is replaced, and its log is kept.
- **A given ID is refused at a taken key.** `reserve` accepts an internal ID, and refuses one that a record that has not failed already has.
- **Removed only when committed.** The element folder stays until its record is committed, so its content is there for any retry.

**Each element ends a merge in one of seven outcomes.**

| Outcome | When | The element |
| --- | --- | --- |
| `merged` | Committed under the fields asked for | Removed |
| `rekeyed` | Committed under other fields, from a clash rule or a parent's final key ([decision 0017](0017-clash-keys-and-the-requested-key.md)) | Removed |
| `needs_decision` | A clash whose rule is fail, or a parent that is missing or failed | Kept. A person gives new fields or discards it |
| `blocked` | Its held parent has not merged | Kept |
| `awaiting_confirmation` | Its rule merges on confirm, or it is older than `max_age` ([decision 0015](0015-merge-trigger-and-age-limit.md)) | Kept |
| `claimed` | Another claimant holds its claim | Kept |
| `incomplete` | The write did not commit, such as a link failure or an unreachable authority | Kept. A later merge retries it |

- **A person decides with two calls.** `Holding.retarget` gives an element new fields, and its held children follow by ID. `Holding.discard` deletes an element, and refuses one that is the parent of other held elements. Nothing else ever deletes unmerged work.
- **New steps can be failed.** The engine calls the checkpoint before `hold`, before each `claim`, and before `clear`, which removes a merged element.

## Consequences

- A merge can be stopped at any step, or run twice, or run on a copy of an element, and it still ends with one record per uuid.
- A shared holding area is safe to merge from two machines. The claim keeps them apart, and the ID check is the real guard.
- Held content lives in exactly one place until it is committed. Copying it to an active link as a backup, as document 11 suggests, is not built yet.
- Holding has no fallback folder. If the holding area cannot be reached, the create fails.
- A stale claim needs a person. That is deliberate: a claim with a time limit could be broken while its claimant is still working.

Details: [Offline operation and holding space](../08-offline-operation-and-holding-space.md), [Write lifecycle and failure handling](../07-write-lifecycle-and-failure-handling.md).
