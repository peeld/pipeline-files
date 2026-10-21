# Configuration model

Everything a tool needs to know about a layout lives in four kinds of plain-text configuration, in YAML that any language can parse, so the same files serve scripts, desktop tools and services.

| Config | Defines | Notes |
| --- | --- | --- |
| Keys | The typed values entities are identified by | Reused across many rules |
| Rules | Named entity types: which keys, in what order, with what parent | Each rule can build on a parent rule |
| Roots | Logical storage bases and where each one is on each machine or operating system | Keeps absolute paths out of every other file |
| Links | Per entity type: the authority, the active and passive links, and their policies | See [Authority and links](06-authority-and-links.md) |

Each kind is a top-level section of the configuration, beside a required `version`. The sections can sit in one file or be spread across a directory of files, as long as each section appears only once. JSON is accepted too. The shape is published as a JSON Schema, `schema/layout.schema.json`, so tools in any language can check a configuration ([decision 0007](decisions/0007-yaml-config-with-json-schema.md)).

**What a key definition carries**

| Property | Purpose | Example |
| --- | --- | --- |
| Type | How the value is stored and compared: `string`, `int` or `date` | Integer, string, date |
| Choices | A fixed list of allowed values | A department code from an approved list |
| Pattern | A regular expression the value's text must match | Two letters followed by four digits |
| Format | How the stored value is written into a name, with `{value}` standing for the value | Integer 14 written as "day14" |
| Pad | Zero-padding for integers | Shot 40 written as "040" |
| Date format | How a date is written, using `%Y`, `%m` and `%d` | 21 October 2026 written as "20261021" |
| Default | A fixed value used when none is given | Version 1 |
| Required | Whether a rule can omit it | Optional sub-folders such as a variant |

Defaults are fixed values. A moving target such as "the latest version" is a question about what exists, so it belongs to a query, not to a key definition. See [Query model](05-query-model.md).

A string key with no pattern or choices refuses anything unsafe in a name on common filesystems: `/`, `\`, the characters Windows forbids, control characters, leading or trailing spaces, a leading or trailing dot, and Windows device names such as `CON` and `AUX`. A leading dot is refused so that hidden files such as `.DS_Store` are never read as entities. Strings are compared in Unicode normal form C, so a name typed on one system matches the same name read back on another.

**What a rule carries.** A rule lists its keys in order, names its parent and root, and gives a template for each backend that needs one. Because a rule inherits its parent's keys, root and template prefix, the shared part of a layout is written once. A rule can mark path segments as optional, and can name attributes that live beside the keys without being part of them.

**Templates.** A template is text with `{key}` placeholders, and `[ ... ]` around an optional group ([decision 0008](decisions/0008-template-syntax-and-strict-parsing.md)). A key can appear more than once, for example as a folder and again in the file name. A child rule's template continues its parent's after a `/`.

```yaml
version: 1

keys:
  project:  {type: string, pattern: "[a-z][a-z0-9]*"}
  sequence: {type: string, pattern: "[A-Z]{2,4}"}
  shot:     {type: int, pad: 3}
  version:  {type: int, format: "v{value}", pad: 3}
  camera:   {type: string, choices: [main, witness, reference]}
  variant:  {type: string, pattern: "[a-z]+", required: false}

roots:
  projects:
    default: /mnt/projects
    platforms: {windows: "P:/projects", darwin: /Volumes/projects}
    hosts: {"render-*": /fast/projects}

rules:
  shot:
    root: projects
    keys: [project, sequence, shot]
    templates:
      fs: "{project}/shots/{sequence}/{sequence}_{shot}"
  media:
    parent: shot
    keys: [version, camera, variant]
    templates:
      fs: "media/{version}/{camera}[_{variant}]"
    attributes: {status: string, artist: string}

links:
  shot:
    tracking: {role: authority}
    files: {role: active}
    review: {role: passive, triggers: [approved]}
```

Here the media for shot 40, version 3, camera main, variant hero is at `fs://projects/alpha/shots/ABC/ABC_040/media/v003/main_hero`. On a render node, that location resolves under `/fast/projects`. On a Mac, it resolves under `/Volumes/projects`. Locations are written as URIs of backend, logical root and relative path ([decision 0009](decisions/0009-location-uris.md)).

**Links.** The `links` section names, for each rule, its authority and its active and passive links, with their settings. Here the tracking database is the authority for shots, and the media and frame rules inherit that, because they declare no links of their own. A link name such as `tracking` is bound to a real backend by the tool that writes, so the configuration holds no connection details ([decision 0012](decisions/0012-link-configuration.md)).

**Design guidelines**

- Keys are constrained tightly enough that a name can always be parsed back unambiguously. If values can contain the separator character, the key's pattern must say so. A name that still splits two ways is refused, never guessed.
- Roots are logical names only. No rule contains an absolute path. A root maps to a real location by host pattern first, then operating system, then a default.
- Configuration is versioned. Data on disk outlives any single set of rules, so each entity records which config version it was created under.
- A separate validation pass checks that required directories exist. Resolution (fields to location) never creates or checks anything on its own.

**Attributes.** Attributes are typed in the configuration and assumed valid when they are used. Nothing in the core checks them. Validation can be added as its own optional layer, or left out.

---

Previous: [Layered architecture](03-layered-architecture.md) | Next: [Query model](05-query-model.md) | [Index](README.md)
