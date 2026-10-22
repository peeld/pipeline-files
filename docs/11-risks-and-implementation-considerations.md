# Risks and implementation considerations

The biggest risks are an abstraction that fits no backend well, and offline work that exists in only one place.

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Leaky abstraction | A lowest-common-denominator interface serves no backend well | Build two backends first (filesystem and a small embedded database). Let backends declare their capabilities |
| Ambiguous parsing | A name that can be split two ways cannot be mapped back to fields | Tight key patterns, and a round-trip test for every rule |
| Rollback that cannot undo | Overwrites, renames and deletes are often not reversible | Roll back only what was created. Define reversibility per operation. Keep an operation log for crashes |
| Holding data is the only copy | A dead disk loses offline work | Durable location, a visible "unmerged" indicator, a backup copy to the first active link, and never auto-delete |
| Stale references after a rename | A path embedded elsewhere stops working | Internal IDs, provisional suffixes for offline work, aliases at merge |
| Filesystem authority drift | Outside changes are only noticed by scanning | Mark it as eventually consistent. Prefer a service authority |
| Configuration drift | Machines disagree about the layout | Versioned config, and the version recorded on every entity |
| Unreliable network file locks | Two mergers could process the same element | Atomic-create claims plus idempotent merge keyed by internal ID |
| Clock differences | Replay order across machines is wrong | Per-client sequence numbers and base revisions, never wall-clock time |

**Decisions settled**

- **Operations while offline.** Every operation can be attempted offline, and none is required to be implemented. The framework makes the call and the implementation does the work. An operation that is not implemented fails when attempted, and each implementation publishes what it supports.
- **Attributes.** Attributes are typed and assumed valid when used. Validation is an optional separate layer that a deployment can add or leave out.
- **Merge trigger.** Held work merges on its own by default. A rule can require a person to confirm each merge ([decision 0015](decisions/0015-merge-trigger-and-age-limit.md)).
- **Holding age limit.** An authority can set `max_age`. Held work older than that waits for a person to confirm it, and is never deleted for its age ([decision 0015](decisions/0015-merge-trigger-and-age-limit.md)).

**Left to the implementation**

These depend on the deployment and can be decided when the relevant phase is built.

- **Language reach.** Whether one core library is enough, or the rules must be read natively from more than one language. The first implementation is in Python, and the configuration has a JSON Schema so other languages can read it directly ([decision 0006](decisions/0006-python-reference-implementation.md)). Whether a second implementation is needed is still open.
- **Migration tooling.** Whether changing an entity type's authority is a one-off script or a supported feature.

---

Previous: [Worked examples](10-worked-examples.md) | Next: [Build order and verification](12-build-order-and-verification.md) | [Index](README.md)
