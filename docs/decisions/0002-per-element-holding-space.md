# 0002: Per-element holding space with uuid identity

**Status:** Accepted. **Date:** 2026-10-21.

## Context

When the authority is unreachable, work still needs to continue, and it must merge back later without corrupting the authority or colliding with other machines.

## Decision

- When the offline policy is hold, new work goes to a holding space instead of the normal namespace.
- Each element has its own holding location, named by a fresh uuid. No coordination between machines is needed.
- The uuid becomes the element's permanent internal ID. Keys are labels; the internal ID is the identity.
- Holding may be on shared storage, but it is not a collaboration space. Each element has one owner, and only the owner merges it or sees it as an overlay by default.
- Elements merge back individually when the authority returns. A child element waits for its parent, because its final key depends on the parent's final key.

## Consequences

- Merging is idempotent. If the authority already has the uuid, the merge is a retry and not a duplicate.
- Clashes are resolved before content takes its final path, which avoids renaming published content.
- Holding data may be the only copy of someone's work, so it needs durable storage, a visible unmerged indicator, and no automatic deletion.

Details: [Offline operation and holding space](../08-offline-operation-and-holding-space.md).
