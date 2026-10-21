# 0004: Operations are optional and fail when not implemented

**Status:** Accepted. **Date:** 2026-10-21.

## Context

Different backends and deployments can support different operations, and an offline machine may be unable to do some of them. Prescribing a fixed set would make the framework unusable on simple backends.

## Decision

- Every operation can be attempted, including while offline, and none is required to be implemented.
- The framework defines each operation and makes the call. The implementation does the actual work.
- An operation that is not implemented fails when it is attempted.
- Each implementation publishes which operations it supports, so callers can check first.

## Consequences

- Backends declare capabilities instead of pretending to be equal.
- No list of operations has to be blocked in offline mode by the framework itself. Whether, for example, a delete works offline is decided by the implementation.

Details: [Layered architecture](../03-layered-architecture.md), [Offline operation and holding space](../08-offline-operation-and-holding-space.md).
