# Layered architecture

Four layers and one shared configuration each do one job, so a backend can be added or replaced without touching any caller.

- **Callers** name a rule and some fields. They never build or parse paths.
- **Query and link engine** resolves queries, and runs every write through the authority, the active links, holding and merge, recording what it does in an operation log.
- **Locators** translate between fields and a backend's own addressing, in both directions.
- **Backends** store content and metadata, and declare what they can do, such as ad-hoc attribute queries or atomic multi-record updates.
- **Configuration** supplies the keys, rules, roots and link policies to every layer above.

The interfaces return field dictionaries and URI-style locations, never raw paths, so nothing above the locators depends on a particular storage type.

The framework defines the operations and makes the calls; each implementation does the actual work and publishes which operations it supports. An operation that is not implemented fails when it is attempted.

```mermaid
flowchart TB
    callers["<b>Tools, scripts and applications</b><br/>Ask for a rule plus fields, such as media for day14.<br/>They never build a path."]
    engine["<b>Query and link engine</b><br/>Reads: partial fields in, whole entities out.<br/>Writes: authority first, then links,<br/>with holding when offline."]
    locators["<b>Locators</b><br/>Translate fields to a path, an object key or a row, and back."]
    fs["<b>Filesystem</b><br/>Directories and files"]
    db["<b>Database</b><br/>Records and attributes"]
    obj["<b>Object storage</b><br/>Objects and prefixes"]
    config["<b>Configuration</b><br/>Keys and key types<br/>Rules and parents<br/>Roots per machine<br/>Link policies"]
    callers --> engine
    engine --> locators
    locators --> fs
    locators --> db
    locators --> obj
    config -.->|read by| engine
    config -.->|read by| locators
```

Callers talk only to the query and link engine; locators and backends sit below it, and one shared configuration drives every layer.

---

Previous: [Core concepts](02-core-concepts.md) | Next: [Configuration model](04-configuration-model.md) | [Index](README.md)
