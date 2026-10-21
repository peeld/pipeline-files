# Configuration model

Everything a tool needs to know about a layout lives in four kinds of plain-text configuration, in a format any language can parse (YAML, TOML or JSON), so the same files serve scripts, desktop tools and services.

| Config | Defines | Notes |
| --- | --- | --- |
| Keys | The typed values entities are identified by | Reused across many rules |
| Rules | Named entity types: which keys, in what order, with what parent | Each rule can build on a parent rule |
| Roots | Logical storage bases and where each one is on each machine or operating system | Keeps absolute paths out of every other file |
| Links | Per entity type: the authority, the active and passive links, and their policies | See [Authority and links](06-authority-and-links.md) |

**What a key definition carries**

| Property | Purpose | Example |
| --- | --- | --- |
| Type | How the value is stored and compared | Integer, string, date |
| Choices | A fixed list of allowed values | A department code from an approved list |
| Pattern | A regular expression the value must match | Two letters followed by four digits |
| Format | How the stored value is written into a name | Integer 14 written as "day14" |
| Default | The value used when none is given | The latest version |
| Required | Whether a rule can omit it | Optional sub-folders such as a variant |

**What a rule carries.** A rule lists its keys in order, names its parent, and gives a template for each backend that needs one. Because a rule inherits its parent's keys and prefix, the shared part of a layout is written once. A rule can mark path segments as optional, and can name attributes that live beside the keys without being part of them.

**Design guidelines**

- Keys are constrained tightly enough that a name can always be parsed back unambiguously. If values can contain the separator character, the key's pattern must say so.
- Roots are logical names only. No rule contains an absolute path.
- Configuration is versioned. Data on disk outlives any single set of rules, so each entity records which config version it was created under.
- A separate validation pass checks that required directories exist. Resolution (fields to location) never creates or checks anything on its own.

**Attributes.** Attributes are typed in the configuration and assumed valid when they are used. Nothing in the core checks them. Validation can be added as its own optional layer, or left out.

---

Previous: [Layered architecture](03-layered-architecture.md) | Next: [Query model](05-query-model.md) | [Index](README.md)
