# Purpose and scope

This plan defines a small, storage-neutral layer that lets tools ask for things by name and fields instead of by path, and keeps those things consistent across a filesystem, a database and cloud storage.

Most tools hard-code locations: "list the files with this extension under this absolute path". The layout conventions end up scattered across scripts, so renaming a folder, moving storage or adding a second copy breaks them. Every field that manages files hits the same wall, whether the files are renders, datasets, CAD models, spreadsheets or instrument output.

The target interaction is: "give me the *media* for *day14*", where *media* is a named rule defined once in configuration and *day14* is a key/value pair. The caller never sees a path unless it asks for one.

**Goals**

- Describe a layout once, in plain configuration files any tool or language can read.
- Resolve in both directions: fields to a location, and a location back to fields.
- Query by fields, with the same call working whether the data lives on disk, in a database or in object storage.
- Declare one authoritative source per entity, and say how every other copy follows it.
- Keep working when the authority is unreachable, then merge safely afterwards.

**Non-goals**

- Not a sync tool: copies are made by declared rules, not by watching folders and guessing.
- Not a content merger: file bytes are never merged. A conflict is settled by versioning up, adding a suffix, or failing.
- Not an access-control system: permissions come from the backends underneath.
- Not a user interface: it is a library and a set of config files that interfaces can sit on.

---

Next: [Core concepts](02-core-concepts.md) | [Index](README.md)
