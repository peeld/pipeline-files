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

**Authority is configuration, and it can move.** Because the authority is declared per entity type, a team can start with files as the authority and later change to a database. A migration moves the records, as described below.

**In configuration** ([decision 0012](decisions/0012-link-configuration.md))

- The `links` section gives each rule a set of named links, each with a role and the settings for that role. A child rule without links uses its parent's.
- A tool binds each link name to a backend when it builds the write engine. An authority must keep records and an operation log, which SQLite does. An active link must be able to realize a record and undo it, which the filesystem does.
- The engine refuses, when it is built, any binding it cannot carry out: an active link with a clash rule other than fail must be able to check for a clash, and the offline policy `hold` needs a holding area.
- A clash rule other than fail needs a key to change, which the rule names. A rule that inherits such a link without that key is refused when the configuration loads ([decision 0017](decisions/0017-clash-keys-and-the-requested-key.md)).
- With the offline policy `read_only`, a write while the authority is unreachable fails with a read-only error, and queries are answered by the first active link that can query.
- With the offline policy `hold`, a write while the authority is unreachable goes to holding. Queries fall back to an active link in the same way, with the owner's held work overlaid ([Offline operation and holding space](08-offline-operation-and-holding-space.md)).

**Running passive links** ([decision 0019](decisions/0019-passive-links-run-on-one-call.md))

- A tool calls `Engine.realize_passive` when its event happens, with the link's name or the event's name. The library has no event system of its own.
- Only a committed record is realized. Each link runs the same steps as an active link, logged in the authority as its own operation, and the record itself never changes.
- The call returns a `PassiveResult` per link. A failed link is reported there, and the next link still runs. Nothing is rolled back or retried, and calling again finishes a run that stopped part way.
- A file entity needs its content, unless the link already holds it, because the authority keeps only its hash.
- A passive link's clash rule must be `fail`, since a committed record cannot change its key.

```python
results = engine.realize_passive("media", media.id, event="approved")
for result in results:
    if not result.realized:
        print(f"{result.link} is behind: {result.error}")
```

**Moving an authority** ([decision 0018](decisions/0018-migration-keeps-identity-history-and-links.md))

A migration is the site's own script. It keeps every record's internal ID, state, revision, requested key and log, and touches no link items. An authority that supports the migration operations, as SQLite does, gives the script what it needs.

| Operation | On | Does |
| --- | --- | --- |
| `claim_rule(rule, claimant)` | The old authority | Claims the rule. From then on every write to its records there raises an unreachable error, so the rule's offline policy applies. Reads still work |
| `records(*rules)` | The old authority | Every record of the rules, in any state, in the order first logged |
| `history(record)` | The old authority | The record's log |
| `restore(record, history)` | The new authority | Writes the record and its log under its own ID. Running it again changes nothing, and a record that differs is refused |

The steps are: claim every rule that moves, restore every record in order, then point tools at the new authority by editing the configuration or binding the link name to the new backend. Then run `recover()` and `merge()` there. Held work, including work held while the move ran, merges into the new authority by its uuid. The claim is never released, so a tool still pointed at the old authority sees the rules as offline and never writes where nobody reads. A move that stops part way finishes when it is run again.

```python
rules = ["shot", "media", "frame"]
for rule in rules:
    old.claim_rule(rule, "migration")
for record in old.records(*rules):
    new.restore(record, old.history(record.id))
```

The reference script is `tests/reference_migration.py`. A site adds its own steps around it, such as a backup first and a check afterwards.

**Caution on filesystem authority.** When the authority is a filesystem, people and other programs change it outside the system. Links then follow by scanning or watching, not instantly, and they are only eventually consistent. This is a supported choice, but it should be a deliberate one. A database or service authority, where every write passes through the system, gives the guarantees described in this plan.

---

Previous: [Query model](05-query-model.md) | Next: [Write lifecycle and failure handling](07-write-lifecycle-and-failure-handling.md) | [Index](README.md)
