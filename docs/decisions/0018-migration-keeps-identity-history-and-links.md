# 0018: Migration is a site's script that keeps identity, history and links, with the old authority offline

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Decision 0001](0001-one-authority-per-entity-type.md) makes the authority a configuration choice per entity type, so moving a type to a new authority needs a migration. [Risks and implementation considerations](../11-risks-and-implementation-considerations.md) left open whether that is a one-off script or a supported feature.

Each site migrates differently, so the steps belong to the site. But some things must hold for every migration. Held elements merge by internal ID ([decision 0016](0016-holding-elements-claims-and-merge.md)), and recovery replays the log ([decision 0013](0013-records-operation-log-and-write-steps.md)). A migration that loses either breaks them.

## Decision

**Migration is implementation defined.** A site writes its own script, and the library gives it what it needs to keep three rules.

- **Identity, history and links are kept.** Every record keeps its internal ID, state, revision, requested key and log. Link items are not touched.
- **The old authority is offline while a rule moves.** Writes to the rule there are treated as unreachable, from the start of the move onwards, so the rule's offline policy applies. With `hold`, new work is held, and it merges into the new authority by its uuid once a tool points there.
- **A migration can be run again.** A migration that stops part way finishes when it is run again.

Switching a tool to the new authority is the site's step. It edits the configuration or rebinds the link name ([decision 0012](0012-link-configuration.md)). A migration does not change keys.

## Consequences

- The phase 6 gate migrates a fixture with a reference script, and checks that identity, history and every link survive.
- A site that wants no refused writes during a migration gives the rule `offline: hold`.
- A tool still pointed at the old authority sees the rule as offline, so it never writes where nobody reads.
- Changing a key's type or the layout is not a migration, and is not supported.

Details: [Authority and links](../06-authority-and-links.md), [Offline operation and holding space](../08-offline-operation-and-holding-space.md).
