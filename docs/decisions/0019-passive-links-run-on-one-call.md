# 0019: A passive link runs on one call, by link or event name, and reports each link's result

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Authority and links](../06-authority-and-links.md) says a passive link runs only on an explicit call or a later event, outside the commit, and that a failure is reported to the caller and never retried silently. [Decision 0012](0012-link-configuration.md) gives a passive link a list of `triggers`, which are event names the domain chooses, and a clash rule. Phase 6 has to say what makes a passive link run, which records it takes, and what a failure leaves.

The library cannot know when something is approved or released. That is the tool's business, and an event system inside the library would have to guess.

## Decision

- **One call.** `Engine.realize_passive(rule, record, link=... or event=...)` realizes one record in passive links. With `link`, it runs that link. With `event`, it runs every passive link whose triggers name the event, in configuration order. The library has no event system: a tool calls this when its event happens.
- **Committed records only.** A record in any other state is refused, because a passive link copies the truth, and a pending, failed or out of sync record is not settled yet.
- **The same link steps.** A passive link runs `realize` with the same `note`, so each item is logged in the authority before it is made. The run is its own operation, and starts with a `passive` step that names the event. The checkpoint names are `passive:<link>`, `realize:<link>`, `<link>:<item>` and `realized:<link>`.
- **Outside the commit.** The record is never changed by a passive link, whatever happens.
- **A result per link.** The call returns one `PassiveResult` per link it ran, with the error if the link failed. A failed link does not stop the next one. Nothing is rolled back and nothing is retried. Calling again is safe, because link steps are idempotent, and it finishes a run that crashed part way.
- **Content comes from the caller.** The authority keeps a file's hash, not its bytes, so a file entity needs its content unless the link already holds it, as with `retry`.
- **Checked before anything runs.** The call needs exactly one of `link` and `event`. An unknown link name, an unbound link, and an event that no rule's passive link names all fail at once. An event that this rule's links do not name runs nothing, as the event can belong to other rules.
- **Binding.** A bound passive link needs `realize`, and a template for the rule. A passive link's clash rule must be `fail`, because a committed record's key can no longer change. Any other clash rule is refused when the engine is built with the link bound. One backend cannot be bound to two of a rule's links.

## Consequences

- When to copy to an archive, a review server or a supplier is decided by the tool, in its own words, and the configuration says which links follow which event.
- A passive link that is behind is visible only in the log and to the caller. The authority keeps no state for it, so recovery never touches it.
- A tool copying a file to a passive link must still have the file's content, or read it from an active link itself.

Details: [Authority and links](../06-authority-and-links.md), [Write lifecycle and failure handling](../07-write-lifecycle-and-failure-handling.md).
