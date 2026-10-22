# 0017: A clash rule changes a key the rule names, the link that finds the clash decides, and the requested key is kept

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Decision 0003](0003-clash-resolution-outcomes.md) settled that a clash resolves by version up, a number suffix, or fail, with the rule set per link. Phase 5 has to say which key a version up raises, where a suffix goes, which link's rule applies, and where the requested key is kept.

A guess, such as "the last integer key", would be wrong for some layout and would break the rule against guessing. A suffix pasted onto a name would also stop the name from parsing back into the same fields.

## Decision

- **The rule names its keys.** `version_key` names the key a `version_up` clash raises. `suffix_key` names the key a `suffix` clash sets. Each must be one of the rule's own int keys, not a parent's, so resolving a clash never moves a parent. A version key sits outside any optional group, because every entity has a version. A suffix key sits in an optional group, because only a clashing entity has one.
- **The suffix is a key.** A template places it, for example `{doctype}[ ({copy})].{ext}`, so a suffixed name parses back like any other. The first suffix is 2, beside the name without one.
- **Checked when the configuration loads.** Every rule whose authority or active link has `version_up` or `suffix` must name the key. A child rule that inherits such links and lacks the key is refused, and declares its own links instead.
- **The link that finds the clash decides.** Before reserving, the engine asks each active link whose clash rule is not fail whether the key is taken there, through a new optional link operation, `clash`. The authority then refuses a key it already holds. The first link to find a clash applies its own rule. A link whose rule is fail is not asked, and a clash it meets while writing fails the write, as before.
- **The next key is one past the highest.** For a version up, the engine asks the authority for the entity's siblings, which share every other key, and tries one past the highest version among them and the one asked for. A suffix works the same way. It tries again up to 100 times, then fails.
- **The same rule for every write.** Online creates and merges resolve clashes the same way.
- **The requested key is kept.** When a record's fields differ from those first asked for, the authority stores the requested fields beside the final ones. SQLite schema version 3 adds a `requested` column and the `claims` table, and upgrades a version 2 database when it is opened.

```yaml
rules:
  deliverable:
    keys: [client, year, quarter, doctype, copy, ext]
    templates:
      fs: "{client}/{year}/{quarter}/{client} {year} {quarter} {doctype}[ ({copy})].{ext}"
    suffix_key: copy
links:
  deliverable:
    dms: {role: authority, clash: suffix}
    drive: {role: active}
```

## Consequences

- A clash changes an entity's label, never its internal ID, and the requested key shows what was asked for.
- Version up works on integer keys only. A letter revision such as `A`, `B`, `AA` needs a defined next value, which is not built yet.
- A layout that wants version up on a parent rule, but not on its children, declares links on each.
- A link clash met while writing, with rollback off, leaves the record out of sync at the requested key. A person must clear the place, because a record cannot be renamed yet.

Details: [Conflict resolution](../09-conflict-resolution.md), [Configuration model](../04-configuration-model.md).
