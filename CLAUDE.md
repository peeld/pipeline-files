# Entity Layout & Storage Abstraction

A storage-neutral layer that lets tools ask for data by rule and fields instead of by path. The design is in `docs/`; the Python package is `src/entitylayout/`.

**Start here:** read `TODO.md` for the current state and the next tasks, then `docs/13-implementation-plan.md`.

## Commands

```sh
.venv/bin/pip install -e ".[test]" -r requirements-docs.txt   # after: python3 -m venv .venv
.venv/bin/pytest                                              # includes slower Hypothesis property tests
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
.venv/bin/mkdocs build --strict                               # the docs site; CI builds it the same way
```

## Conventions

- Work proceeds in the phases in `docs/12-build-order-and-verification.md`. A phase is done only when its gate test passes. Tick it off in doc 13 and update `TODO.md`.
- The decision records in `docs/decisions/` are constraints. Record a new settled choice as the next numbered decision, and list it in `docs/decisions/README.md`, `docs/README.md` and `mkdocs.yml`.
- Docs style: short plain sentences, sentence-case headings, bold lead-ins, tables, and Previous/Next footers. Link to code by repository path in backticks, not relative links, because `mkdocs --strict` rejects links outside `docs/`.
- Each worked example in doc 10 is a fixture in `tests/fixtures/`. New features are tested against all five.
- Errors are loud: never guess on an ambiguous name, never quietly skip a bad value. Raise a `LayoutError` subclass that names the rule, key or path at fault.
- Python 3.10 or later, ruff line length 120.
- Each phase is built on its own branch off `main` (`phase-N-...`), as one commit. When its gate and all checks pass, fast-forward `main` to it and push `main`. No PRs.
- Backend operations are listed in `OPERATIONS` in `src/entitylayout/backends/base.py`, and a backend supports the ones it overrides (decision 0004). Authority, link and migration operations are grouped in `AUTHORITY_OPERATIONS`, `LINK_OPERATIONS` and `MIGRATION_OPERATIONS`.
- Write flow rules (decision 0013): log before acting. A link step calls `note(item)` before it makes each item, and undo removes only logged items that are unchanged. Every new step in `src/entitylayout/engine.py` calls `self.checkpoint(name)` first, so the phase 4 gate (`tests/test_write_gate.py`) can fail it.
- Holding rules (decision 0016): nothing but `Holding.discard`, a person's call, deletes unmerged work. A merge reserves under the element's uuid, so every merge path must stay idempotent by internal ID, and the phase 5 gate (`tests/test_merge_gate.py`) replays a crash at every merge step.
- Passive links and migration (decisions 0018 and 0019): a passive link never changes its record and is never retried. A write to a rule that a migration has claimed raises `UnreachableError`, so every new write path in an authority must check the rule claim, and the phase 6 gate (`tests/test_migration_gate.py`) replays a crash at every migration step.
- A setting the engine cannot carry out yet is refused when the `Engine` is built, never treated as a default. Remove the refusal in `Engine._check` when the feature lands.
- A change to the SQLite tables bumps `SCHEMA_VERSION` in `src/entitylayout/backends/sqlite.py` and adds an upgrade from the previous version, tested on a file built the old way (see `_version_1_database` in `tests/test_sqlite.py`).
