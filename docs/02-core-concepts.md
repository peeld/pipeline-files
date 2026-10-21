# Core concepts

The design rests on thirteen terms, and the split between keys and attributes is the one decision every rule has to make deliberately.

| Term | Meaning | Generic example |
| --- | --- | --- |
| Entity | A tracked thing with an identity and optional attributes | A shot, a dataset run, a part revision, a quarterly report, a sample |
| Key | A typed value that is part of an entity's identity | project, day, version, sample id |
| Attribute | A value about the entity that is not part of its identity | owner, status, notes, review state |
| Fields | A plain dictionary of key values. A full dictionary names one entity; a partial one is a query | {project: alpha, day: 14} |
| Rule | A named pattern built from keys that describes one kind of entity and where it lives. A rule is an entity type | media, results, drawing, invoice |
| Root | A logical storage base, mapped to a real location per machine or operating system | projects, archive, scratch |
| Locator | The per-backend translation between fields and a location: a path, an object key, a table lookup | A path template, a key prefix, a primary key |
| Backend | A place where data lives | Filesystem, database, object storage |
| Authority | The single backend whose record is the truth for an entity | The database |
| Active link | A copy that is created and kept in step as part of every write | The local directory tree |
| Passive link | A copy made only on an explicit call or a later event | A cloud archive |
| Holding space | A staging area for an element when the authority is unreachable | A uuid-named folder beside the final root |
| Internal ID | A uuid that never changes. Keys are labels; the ID is the identity | Assigned when the element is first created |

**Keys versus attributes.** Keys are what make an entity unique, so they appear in its location and are expensive to change. Attributes can change freely and are never encoded in a path. A rule that confuses the two either renames files every time a status changes, or cannot tell two entities apart.

---

Previous: [Purpose and scope](01-purpose-and-scope.md) | Next: [Layered architecture](03-layered-architecture.md) | [Index](README.md)
