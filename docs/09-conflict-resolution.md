# Conflict resolution

Every conflict is settled by one of three outcomes: version up, add a number suffix, or fail the operation. There is no content merging, so a conflict never needs human interpretation of file bytes.

| Conflict | Detected by | Typical resolution |
| --- | --- | --- |
| Two creations want the same key | The authority already has that key under a different internal ID | Version up if the rule has a version key, otherwise suffix, or fail |
| An edit was based on an old revision | The stored base revision differs from the authority's current one | Fail, or save the edit as a new revision |
| A file exists with different content | The content hash differs from the recorded hash | Version up, suffix, or fail. Never overwrite |
| A parent is missing or was changed | The parent's internal ID cannot be found or its key changed | Wait for the parent's merge, then recompute the child's key |

**Revision stamps.** Every replicated record, such as a sidecar, carries the authority revision it was derived from and a hash of what was written. With those two values a tool can tell whether a sidecar is stale, and whether someone has edited it by hand.

**Hand-edited sidecars are proposals.** When a stamp shows a sidecar was edited, the change is treated as a proposed edit against the recorded base revision. If the authority has not moved since, the edit is applied. If it has, the clash rule decides. One path handles both hand edits and offline edits.

**Identity survives resolution.** Internal IDs never change, so a suffix or a new version alters the label of an entity without breaking references to it. The originally requested key is stored beside the final one, so it is always possible to see what was asked for.

**In practice** ([decision 0017](decisions/0017-clash-keys-and-the-requested-key.md))

- A rule names the keys a clash rule may change: `version_key` for a version up, and `suffix_key` for a suffix. Each is one of the rule's own integer keys, so a clash never moves a parent. The suffix key sits in an optional group of the template, so a name such as `Acme 2026 Q1 report (2).docx` parses back like any other.
- The link that finds the clash decides. Active links whose rule is not fail are checked before the authority reserves the key. Then the authority refuses a key it holds.
- A version up takes one past the highest version among the entity's siblings. A suffix starts at 2. Online creates and merges follow the same rules.
- The authority stores the requested fields beside the final ones whenever they differ.
- Hand-edited sidecars are detected, but not yet applied as proposals, because there are no updates yet.

**Prevent clashes where possible.** Resolution after the fact is the expensive case. Cheaper options include giving offline work a provisional machine-tagged suffix from the start, or handing each client a block of version numbers in advance. Both make most merges clash-free.

---

Previous: [Offline operation and holding space](08-offline-operation-and-holding-space.md) | Next: [Worked examples](10-worked-examples.md) | [Index](README.md)
