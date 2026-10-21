# 0005: Attributes are typed and not validated on use

**Status:** Accepted. **Date:** 2026-10-21.

## Context

Entities carry attributes (owner, status, parameters and so on) beside their keys. Checking every attribute on every use would add cost and coupling to the core.

## Decision

- Attributes are typed in the configuration.
- They are assumed to be valid when used. The core does not check them.
- Validation is an optional separate layer. A deployment can add it or leave it out.

## Consequences

- The core stays small, and validation rules can differ between deployments without changing it.
- Anything that needs guaranteed-valid attributes must include the validation layer.

Details: [Configuration model](../04-configuration-model.md).
