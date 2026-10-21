# 0012: Links are named per rule, with a role and settings, and bound to backends at run time

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Decision 0001](0001-one-authority-per-entity-type.md) gives each entity type one authority, plus active and passive links. Phase 4 needs a configuration shape for them. The settings come from [Authority and links](../06-authority-and-links.md): role, order, triggers, rollback, clash rule and offline policy.

A configuration file is shared between machines, so it cannot hold a database connection or a server address that differs per machine. Most layouts also give every rule in a family the same links.

## Decision

- **Per rule, by name.** The `links` section maps a rule name to its links. Each link has a name and settings, and the settings always include a `role`: `authority`, `active` or `passive`.
- **Names are bound at run time.** A link name, such as `tracking` or `files`, names a store. A tool binds each name to a real backend when it builds the write engine. The configuration says what the links are, and the tool says where they are on this machine.
- **Settings by role.** Each role accepts only the settings that mean something for it. Any other setting is refused.

| Role | Settings | Defaults |
| --- | --- | --- |
| Authority | `offline`: `fail`, `read_only` or `hold`. `clash`: `fail`, `version_up` or `suffix` | `fail`, `fail` |
| Active | `order`: an integer. `rollback`: true or false. `clash` | No order, `true`, `fail` |
| Passive | `triggers`: a list of event names. `clash` | No triggers, `fail` |

- **Exactly one authority** per rule. A rule with more than one active link needs a distinct `order` on each, and they run lowest first.
- **Active links run on commit.** They take no triggers. A passive link with no triggers runs only on an explicit call.
- **Events are named freely.** Trigger names such as `approved`, `released` or `published` are the domain's own words, not a fixed list.
- **Inherited from the parent.** A rule without links uses its nearest ancestor's links, whole. A rule that declares links replaces them. Nothing is merged.
- **Unbuilt settings fail when bound.** The engine refuses, when it is built, any setting it cannot carry out yet. Today that is the clash rules `version_up` and `suffix`, which need the merge in phase 5, and the offline policy `hold`. It never quietly treats them as `fail`.

```yaml
links:
  shot:
    tracking: {role: authority, offline: read_only}
    files: {role: active}
    review: {role: passive, triggers: [approved]}
```

## Consequences

- One configuration works on every machine. Only the binding of names to backends differs.
- Child rules usually need no links of their own. A child that should live somewhere else declares its own set.
- A store bound to two of one rule's links is refused, because a rollback would undo the same place twice.
- Passive links can be left unbound until their triggers are built in phase 6.

Details: [Authority and links](../06-authority-and-links.md), [Configuration model](../04-configuration-model.md).
