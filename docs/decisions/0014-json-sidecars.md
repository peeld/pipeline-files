# 0014: Sidecars are hidden JSON files, stamped with revision and hash

**Status:** Accepted. **Date:** 2026-10-21.

## Context

A filesystem link has no place for attributes or identity, so each entity gets a sidecar. [Conflict resolution](../09-conflict-resolution.md) requires every replicated record to carry the authority revision it came from and a hash of what was written, so a tool can tell a stale sidecar from a hand-edited one. The sidecar must never be read as an entity by a filesystem query.

## Decision

- **JSON.** The format is a JSON object, which every language reads and a person can edit. It is UTF-8, indented, with keys in a fixed order.
- **Where it sits.** A directory entity's sidecar is `.entitylayout.json` inside the directory. A file entity's sidecar is beside the file, named `.<file name>.entitylayout.json`. Both start with a dot, and key values cannot start with a dot, so a walk never reads one as an entity.
- **What it holds.** `format` (`entitylayout.sidecar`), `format_version` (1), the internal `id`, the `rule`, the `location` URI, the `fields`, the `attributes`, the `config_version`, the authority `revision` and the file's `content_hash` (null for a directory). Dates are ISO-8601 text.
- **The stamp.** A last `hash` field holds a SHA-256 hash of every other field, written as canonical JSON. If the body no longer matches the hash, the sidecar has been edited by hand. If its revision is below the authority's, it is stale.
- **Content hashes** are SHA-256, written `sha256:<hex>`, and the same in the authority and the sidecar.
- **Written whole.** Sidecars and files are written to a temporary file named after the record, then moved into place, so no reader ever sees part of one.

## Consequences

- A tool can check a sidecar against the authority without reading the content.
- A hand-edited sidecar is detected now. Applying it as a proposed edit comes with the merge in phase 5.
- A sidecar that differs from the one a create would write is a clash, and the create fails rather than replace it.

Details: [Conflict resolution](../09-conflict-resolution.md), [Write lifecycle and failure handling](../07-write-lifecycle-and-failure-handling.md).
