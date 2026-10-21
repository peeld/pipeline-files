# 0006: Python reference implementation, language-neutral configuration

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Risks and implementation considerations](../11-risks-and-implementation-considerations.md) left "language reach" open: one core library, or rules read natively from more than one language. Code has to be written in something before that question can be answered from experience.

## Decision

- The first implementation is a Python package, `entitylayout`, supporting Python 3.10 and later.
- The configuration stays language-neutral. Its shape is published as a JSON Schema, so another language can read and check the same files without going through Python.
- The behavior every implementation must share is pinned by tests that run on the worked-example fixtures, not by the Python code itself.

## Consequences

- Tools in other languages can either call the Python package or read the configuration directly. That choice can wait until a real tool needs it.
- Anything a second implementation must match, such as key formatting and template parsing, is written down in [Configuration model](../04-configuration-model.md) and decision 0008, not left implicit in the code.

Details: [Implementation plan](../13-implementation-plan.md).
