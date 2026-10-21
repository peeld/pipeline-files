# 0009: Locations are URIs of backend, logical root and relative path

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Layered architecture](../03-layered-architecture.md) says interfaces return URI-style locations, never raw paths, but did not fix their shape.

## Decision

- A location is written `<backend>://<root>/<path>`, for example `fs://projects/alpha/day14`.
- `<backend>` names the template used, such as `fs` or `object`. `<root>` is the logical root name from the configuration. `<path>` is the formatted template, percent-encoded.
- Turning a location into a real path is a separate call that resolves the root for the current machine. The reverse call finds the deepest root that contains a real path.

## Consequences

- A location means the same thing on every machine, so it can be stored, logged and shared.
- Real paths appear only at the edge, when a tool actually opens a file.

Details: [Configuration model](../04-configuration-model.md).
