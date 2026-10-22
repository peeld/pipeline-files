# TODO: handoff for the next session

**Last updated:** 2026-10-21. **Next up:** choose from "Next" below.

## Where things stand

- All six phases of the [build order](docs/12-build-order-and-verification.md) are built, and all six gates pass.
- All six phases are on `main` and pushed to `origin`, one commit each. Each phase is built on its own branch, then `main` is fast-forwarded to it and pushed. There are no PRs.
  - Phase 1: keys, rules, roots, templates, two-way resolution, CLI, JSON Schema.
  - Phase 2: backend interface, filesystem backend, queries and filters.
  - Phase 3: SQLite backend, `create`, attribute filters, capability flags, the optional validator, `query --db`.
  - Phase 4: the `links` section, records with states, the operation log (SQLite schema 2), the write engine with rollback and recovery, filesystem `realize` and `undo`, sidecars.
  - Phase 5: holding and merge, the owner's overlay, claims, the clash rules `version_up` and `suffix` with the requested key kept (SQLite schema 3), and decisions 0015 to 0017.
  - Phase 6: `Engine.realize_passive` for passive links, the migration operations `claim_rule`, `release_rule`, `records` and `restore`, a reference migration script, and decisions 0018 and 0019. No schema change.
- Locally, the tests pass on Python 3.10 on Linux, with SQLite 3.37. `.github/workflows/tests.yml` also covers 3.12 on Linux, Windows and macOS. All four CI jobs pass.

## Before starting

1. Set up and check that everything passes:

   ```sh
   python3 -m venv .venv && .venv/bin/pip install -e ".[test]" -r requirements-docs.txt
   .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
   .venv/bin/pytest
   .venv/bin/mkdocs build --strict
   ```

2. Read [docs/13-implementation-plan.md](docs/13-implementation-plan.md), especially "Known gaps and follow-ups".
3. New work that is not a gap fix needs its own decision first, and its own branch off `main`.

## Where the phase 6 code is

| To change | Look at |
| --- | --- |
| Running passive links, and the binding checks for them | `realize_passive` and `_check` in `src/entitylayout/engine.py` |
| The migration operations and the rule claim | `src/entitylayout/backends/base.py`, and `claim_rule`, `records`, `restore` and `_refuse_if_moving` in `src/entitylayout/backends/sqlite.py` |
| The reference migration script | `tests/reference_migration.py` |
| Unit tests and the gate | `tests/test_passive.py`, `tests/test_migration.py`, `tests/test_migration_gate.py` |

## Next

- [x] Get the macOS CI job passing. It failed from phase 4 until `e7307c4`, because generated key values could hold an unassigned code point. All four jobs now pass.
- [ ] Updates through the write flow, with a base revision. This needs its own decision. Applying hand-edited sidecars and holding offline edits follow from it.
- [ ] Add `create`, `recover`, `merge` and `realize-passive` commands to the command line.

Smaller gaps, such as letter revisions, `--newest` grouping, permission errors in a walk, and a passive link reading a file's content from an active link, are listed in doc 13 under "Known gaps and follow-ups". Pick them up when a real layout needs them.
