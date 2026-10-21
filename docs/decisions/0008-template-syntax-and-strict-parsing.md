# 0008: Template syntax, and parsing that refuses ambiguity

**Status:** Accepted. **Date:** 2026-10-21.

## Context

Rules need a template for each backend that works in both directions. The [risks](../11-risks-and-implementation-considerations.md) name ambiguous parsing as a core risk: a name that can be split two ways cannot be mapped back to fields.

## Decision

- A template is literal text with `{key}` placeholders. `/` separates path segments.
- `[ ... ]` marks an optional group, written only when its keys are given. Groups do not nest, and every key in a group must be declared `required: false`.
- A key may appear more than once in a template, and every occurrence must parse to the same value.
- A child rule's template continues its parent's template for the same backend after a `/`. A template must use exactly the rule's keys, including inherited ones.
- Templates are relative. A leading `/`, a drive letter, a backslash, or an empty, `.` or `..` segment is a configuration error.
- Parsing tries every way of splitting the text. If none fits, it reports no match. If more than one fits, it raises an ambiguity error and never picks one.
- Key text is canonical: a value is accepted only if formatting it again gives exactly the same text. For example, `7` is refused for a key padded to `007`.

## Consequences

- Loose keys are allowed. A layout fails only on names that really are ambiguous, and the round-trip test finds those.
- Literal `{`, `}`, `[` and `]` cannot appear in templates.

Details: [Configuration model](../04-configuration-model.md).
