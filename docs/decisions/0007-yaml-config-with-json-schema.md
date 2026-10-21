# 0007: YAML configuration in named sections, checked by a JSON Schema

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Configuration model](../04-configuration-model.md) allowed YAML, TOML or JSON. Tools need one answer, and the files need a shape that a person can edit and a program can check.

## Decision

- Configuration is YAML. JSON is also accepted, because YAML parsers read it.
- A configuration has five top-level sections: `version`, `keys`, `rules`, `roots` and `links`. Only `version` is required.
- A configuration is either one file or a directory of files. In a directory, every `.yaml`, `.yml` and `.json` file is read and the sections are merged. A section may appear in only one file.
- The shape of the merged configuration is defined by a JSON Schema at `schema/layout.schema.json`. Cross-references, such as a rule naming an undefined key, are checked by the loader.

## Consequences

- Teams can keep keys, rules and roots in separate files and change roots per site without touching rules.
- TOML is not supported. It can be added later as another reader that produces the same sections.

Details: [Configuration model](../04-configuration-model.md).
