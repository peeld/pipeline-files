# Entity Layout & Storage Abstraction

**Ask for your data by what it is, not where it lives.**

This project designs a small, storage-neutral layer that lets tools ask for things by name and fields instead of by path. It also keeps those things consistent across a filesystem, a database and cloud storage.

- **Read the design as a website:** https://peeld.github.io/pipeline-files/
- **Read it on GitHub:** start at [docs/README.md](docs/README.md)

## The problem

Almost every tool that works with files has the folder layout written into it: "list the files with this extension under this absolute path." Those conventions spread across scripts, plugins and people's habits. Then someone renames a folder, moves to new storage or adds a cloud copy, and things quietly break.

This happens in any field that manages lots of files:

- renders and plates in visual effects
- experiment runs in data science
- CAD models and drawings in engineering
- client reports on a shared drive
- raw instrument output in a lab

Each team ends up building its own fragile version of the same solution.

## The idea

Describe the layout **once**, in plain configuration files, then let every tool ask for what it needs in everyday terms:

> "Give me the **media** for **day 14**."

The caller never builds a path. The layer works out where that data lives, whether it's on disk, in a database or in object storage, and it can also turn a location back into the fields that describe it. Change the layout or the storage, and the tools keep working.

## Why it's useful

- **Layouts can change without breaking tools.** Rename, restructure or move storage in one place, not in every script.
- **The same query works on any storage.** A filesystem, a database and the cloud all answer the same question the same way.
- **There is one source of truth.** Each kind of data has a single authority, and every other copy follows it by clear, declared rules, with no folder-watching guesswork.
- **Work continues offline.** When the authority can't be reached, new work is held safely and merges back on reconnect. Clashes are settled predictably.
- **It isn't tied to one language or industry.** The configuration is plain text that any tool can read, and the model fits very different fields just by changing that configuration.

It is deliberately **not** a sync tool, a file merger, a permissions system or a user interface. It's a foundation that those things can sit on.

## Current state

This is an **early-stage design, open for comment**, with the first phase of code in place.

- The full design is written up across [thirteen short documents](docs/README.md), with diagrams and worked examples from five different fields.
- Nine decisions are settled and recorded in [docs/decisions/](docs/decisions/README.md).
- Everything else is a proposal, and some questions are [deliberately left open](docs/11-risks-and-implementation-considerations.md).
- Implementation runs in [six phases](docs/12-build-order-and-verification.md), each with a test gate. **Phase 1 is built:** a layout described once in configuration, resolved from fields to a location and back. Progress is tracked in the [implementation plan](docs/13-implementation-plan.md).
- The first usable version, after phase 3, will query by fields on two storage backends.

## Try it

Requires Python 3.10 or later.

```sh
python -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest

# Fields to a location, and back
.venv/bin/entitylayout tests/fixtures/vfx locate media project=alpha sequence=ABC shot=40 version=3 camera=main
.venv/bin/entitylayout tests/fixtures/vfx parse fs://projects/alpha/shots/ABC/ABC_040/media/v003/main
```

The `tests/fixtures/` directory holds a configuration for each of the five worked examples.

## Get involved

Feedback is most valuable now, while the design is still taking shape. These are especially helpful:

- **Does this match a problem you have?** Tell us about your field and where your current setup hurts.
- **Would it fit your data?** Try sketching your own layout against the [worked examples](docs/10-worked-examples.md).
- **Can you poke holes in it?** The [risks and open questions](docs/11-risks-and-implementation-considerations.md) are a good place to start.

Please open an issue or a pull request that names the document and section it refers to, and keep to one topic per issue.
