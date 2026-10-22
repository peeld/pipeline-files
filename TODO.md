# TODO: handoff for the next session

**Last updated:** 2026-10-21. **Next up:** phase 6, passive links and migration.

## Where things stand

- Phases 1 to 5 of the [build order](docs/12-build-order-and-verification.md) are built, and all five gates pass.
- All five phases are on `main` and pushed to `origin`, one commit each. Each phase is built on its own branch, then `main` is fast-forwarded to it and pushed. There are no PRs.
  - Phase 1: keys, rules, roots, templates, two-way resolution, CLI, JSON Schema.
  - Phase 2: backend interface, filesystem backend, queries and filters.
  - Phase 3: SQLite backend, `create`, attribute filters, capability flags, the optional validator, `query --db`.
  - Phase 4: the `links` section, records with states, the operation log (SQLite schema 2), the write engine with rollback and recovery, filesystem `realize` and `undo`, sidecars.
  - Phase 5: holding and merge, the owner's overlay, claims, the clash rules `version_up` and `suffix` with the requested key kept (SQLite schema 3), and decisions 0015 to 0017.
- Locally, the tests pass on Python 3.10 on Linux, with SQLite 3.37. `.github/workflows/tests.yml` also covers 3.12 on Linux, Windows and macOS. It first ran when `main` was pushed on 2026-10-21, and its results have not been checked yet.

## Before starting

1. Branch `phase-6-passive-links-and-migration` off `main`. When the gate and all checks pass, fast-forward `main` to it and push `main`.
2. Set up and check that everything passes:

   ```sh
   python3 -m venv .venv && .venv/bin/pip install -e ".[test]" -r requirements-docs.txt
   .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
   .venv/bin/pytest
   .venv/bin/mkdocs build --strict
   ```

3. Read [docs/13-implementation-plan.md](docs/13-implementation-plan.md), especially "Design notes for phase 6" and "Known gaps and follow-ups". Then read doc 06, and decisions 0001, 0012, 0013 and 0016.

## Where the phase 5 code is

| To change | Look at |
| --- | --- |
| `merge` and `max_age` on the authority | `src/entitylayout/links.py` |
| `version_key`, `suffix_key`, and the check that a clash rule has its key | `_clash_key` and `_read_links` in `src/entitylayout/layout.py` |
| Held elements, manifests, claims, `retarget` and `discard` | `src/entitylayout/holding.py` |
| Holding on create, the overlay, clash rules, merge, recovery claims | `src/entitylayout/engine.py` (the step names are in its docstring) |
| Reserving under a given ID, requested keys, claims, schema 3 | `src/entitylayout/backends/sqlite.py` |
| The `clash` probe | `src/entitylayout/backends/filesystem.py` |
| Unit tests and the gate | `tests/test_holding.py`, `tests/test_merge_gate.py` |

## Phase 6 tasks

- [ ] Decide whether migration is a script or a supported tool ([open questions](docs/11-risks-and-implementation-considerations.md)), and record it as a decision.
- [ ] Event triggers for passive links: a passive link realizes a committed record on its trigger, outside the commit, and reports failures to the caller.
- [ ] An object-storage backend with `realize`, `undo` and `clash`.
- [ ] Migration of an entity type to a new authority that keeps internal IDs, states, revisions, requested keys and the log.
- [ ] Write the phase 6 gate: a migrated entity type keeps identity, history and every link.
- [ ] Update the docs: tick phase 6 in doc 13, update the status lines in `README.md` and `docs/README.md`, and refresh this file.

## Smaller follow-ups

Details are in doc 13 under "Known gaps and follow-ups".

- [ ] Check the Windows and macOS CI runs from the first push to `main`, and fix anything case- or path-length related. Check the SQLite version on each runner supports JSON functions (`json_each`) and partial indexes.
- [ ] Updates through the write flow, with a base revision. Then apply hand-edited sidecars as proposals (`Sidecar.edited` and `stale()` detect them), and hold offline edits as well as creates.
- [ ] Version up for letter revisions, such as the industrial design fixture's `revision`.
- [ ] A backup copy of held content to the first active link, and a local fallback when the holding area is unreachable.
- [ ] Add `create`, `recover` and `merge` commands to the command line.
- [ ] Let the `--newest` option choose its grouping keys (`within=`).
- [ ] Decide how a filesystem walk handles a permission error.
- [ ] An import tool that loads a directory tree into SQLite needs to create parent rows too.
