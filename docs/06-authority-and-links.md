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

**In configuration** ([decision 0012](decisions/0012-link-configuration.md))

- The `links` section gives each rule a set of named links, each with a role and the settings for that role. A child rule without links uses its parent's.
- A tool binds each link name to a backend when it builds the write engine. An authority must keep records and an operation log, which SQLite does. An active link must be able to realize a record and undo it, which the filesystem does.
- The engine refuses, when it is built, any binding it cannot carry out: an active link with a clash rule other than fail must be able to check for a clash, and the offline policy `hold` needs a holding area.
- A clash rule other than fail needs a key to change, which the rule names. A rule that inherits such a link without that key is refused when the configuration loads ([decision 0017](decisions/0017-clash-keys-and-the-requested-key.md)).
- With the offline policy `read_only`, a write while the authority is unreachable fails with a read-only error, and queries are answered by the first active link that can query.
- With the offline policy `hold`, a write while the authority is unreachable goes to holding. Queries fall back to an active link in the same way, with the owner's held work overlaid ([Offline operation and holding space](08-offline-operation-and-holding-space.md)).

**Caution on filesystem authority.** When the authority is a filesystem, people and other programs change it outside the system. Links then follow by scanning or watching, not instantly, and they are only eventually consistent. This is a supported choice, but it should be a deliberate one. A database or service authority, where every write passes through the system, gives the guarantees described in this plan.

---

Previous: [Query model](05-query-model.md) | Next: [Write lifecycle and failure handling](07-write-lifecycle-and-failure-handling.md) | [Index](README.md)
