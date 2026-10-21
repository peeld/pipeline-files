# 0010: Filesystem queries are strict and fail loudly

**Status:** Accepted. **Date:** 2026-10-21.

## Context

A filesystem holds whatever people and other programs put there. A query has to decide what to do with names that do not fit a rule, names that fit it two ways, and values that would cross a directory boundary.

## Decision

- A name that does not fit the rule is skipped. Real trees are full of such names, such as notes, thumbnails and hidden files, and they are not entities.
- A name that fits the rule in more than one way raises an error, even when the query's own fields would pick one reading. It points to a layout that needs tighter keys, and quietly choosing would return the wrong entity.
- Query values are checked against their keys before the walk, so a typo fails instead of returning nothing.
- A filesystem template cannot use a key whose values could contain `/`. This is checked when the backend is created.
- By default, string keys refuse names that start with a dot and Windows device names such as `CON` and `AUX`. A key with its own pattern or choices decides for itself.

## Consequences

- A query either returns exactly the entities that fit the rule or fails with a reason. It never returns a partial or guessed answer.
- One badly named directory can make a query fail until it is renamed or the layout is tightened. That is deliberate, but the error has to name the path, and it does.

Details: [Query model](../05-query-model.md).
