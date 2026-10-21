# Authority and links

Each entity type names exactly one authority, and every other place the entity exists is either an active link or a passive link. The authority's record is the truth; links are copies that follow it.

| Role | When it changes | If it fails |
| --- | --- | --- |
| Authority | First, on every write | The whole operation stops and nothing else is touched |
| Active link | As part of the same write, in a declared order | Roll back if possible (the default), otherwise mark the link out of sync and retry |
| Passive link | Only on an explicit call or a later triggering event | Reported to the caller. Never retried silently |

**One mechanism, two policies.** Active and passive links are the same thing: an action bound to an event (created, committed, changed, approved, deleted). An active link runs that action synchronously as part of the commit. A passive link runs it later, on demand or when another event fires, such as "copy to the archive when the item is approved". Per-link settings are the only difference:

| Setting | Meaning |
| --- | --- |
| Role | Authority, active or passive |
| Order | Position among the active links |
| Triggers | Which events run the link (active links use the commit event) |
| Rollback | Undo the authority change if this link fails. On by default for active links |
| Clash rule | What to do on a key clash: version up, add a suffix, or fail |
| Offline policy | Fail, read-only, or hold new work for later merge |

**Passive means "not automatic", not "unknown".** A passive link still has a locator, so its contents can be read and, if wanted, imported into the authority. Nothing writes to it unless told to.

**Authority is configuration, and it can move.** Because the authority is declared per entity type, a team can start with files as the authority and later change to a database. That needs a migration tool, so plan for one.

**Caution on filesystem authority.** When the authority is a filesystem, people and other programs change it outside the system. Links then follow by scanning or watching, not instantly, and they are only eventually consistent. This is a supported choice, but it should be a deliberate one. A database or service authority, where every write passes through the system, gives the guarantees described in this plan.

---

Previous: [Query model](05-query-model.md) | Next: [Write lifecycle and failure handling](07-write-lifecycle-and-failure-handling.md) | [Index](README.md)
