# TODO: handoff for the next session

**Last updated:** 2026-10-21. **Next up:** phase 5, holding and merge.

## Where things stand

- Phases 1 to 4 of the [build order](docs/12-build-order-and-verification.md) are built, and all four gates pass.
- All four phases are on `main` and pushed to `origin`, one commit each. Each phase was built on its own branch, then `main` was fast-forwarded to it. There are no PRs.
  - Phase 1: keys, rules, roots, templates, two-way resolution, CLI, JSON Schema.
  - Phase 2: backend interface, filesystem backend, queries and filters.
  - Phase 3: SQLite backend, `create`, attribute filters, capability flags, the optional validator, `query --db`.
  - Phase 4: the `links` section, records with states, the operation log (SQLite schema 2), the write engine with rollback and recovery, filesystem `realize` and `undo`, sidecars.
- Locally, the tests pass on Python 3.10 on Linux, with SQLite 3.37. `.github/workflows/tests.yml` also covers 3.12 on Linux, Windows and macOS. It first ran when `main` was pushed on 2026-10-21, and its results have not been checked yet.

## Before starting

1. Branch `phase-5-holding-and-merge` off `main`. When the gate and all checks pass, fast-forward `main` to it and push `main`.
2. Set up and check that everything passes:

   ```sh
   python3 -m venv .venv && .venv/bin/pip install -e ".[test]" -r requirements-docs.txt
   .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
   .venv/bin/pytest
   .venv/bin/mkdocs build --strict
   ```

3. Read [docs/13-implementation-plan.md](docs/13-implementation-plan.md), especially "Design notes for phase 5" and "Known gaps and follow-ups". Then read docs 08 and 09, and decisions 0002, 0003, 0012, 0013 and 0014.

## Where the phase 4 code is

| To change | Look at |
| --- | --- |
| The `links` settings and their checks | `src/entitylayout/links.py`, read from `_read_links` in `src/entitylayout/layout.py` |
| Record states, sidecar format, hashes | `src/entitylayout/records.py` |
| The write flow, rollback, recovery, offline policies | `src/entitylayout/engine.py` (the step names are in its docstring) |
| Authority storage and the operation log | `src/entitylayout/backends/sqlite.py` |
| Filesystem `realize` and `undo` | `src/entitylayout/backends/filesystem.py` |
| Unit tests and the gate | `tests/test_engine.py`, `tests/test_links.py`, `tests/test_write_gate.py` |

## Phase 5 tasks

- [ ] Decide the holding age limit and the merge trigger ([open questions](docs/11-risks-and-implementation-considerations.md)), and record them as decisions.
- [ ] Per-element holding: a uuid folder with a manifest, the content and a sidecar. The offline policy `hold` sends new work there when the authority is unreachable.
- [ ] An overlay for the owner: their held elements appear in queries, flagged `provisional`.
- [ ] Claim markers made by atomic create, so two machines never merge the same element. Use them to make `recover()` safe to run concurrently too.
- [ ] Merge through the write flow, idempotent by internal ID. `reserve` needs to accept a given ID and refuse a different one at the same key.
- [ ] Merge in dependency order, parents first. A child whose parent has not merged reports that it is blocked.
- [ ] The clash rules `version_up` and `suffix`, keeping the requested key beside the final one (SQLite schema 3). Remove the engine's refusals of `hold`, `version_up` and `suffix`.
- [ ] Hand-edited sidecars as proposed edits against their base revision. `Sidecar.edited` and `stale()` already detect them.
- [ ] Write the phase 5 gate: replayed offline sessions with injected clashes resolve exactly as configured.
- [ ] Update the docs: tick phase 5 in doc 13, update the status lines in `README.md` and `docs/README.md`, and refresh this file.

## Smaller follow-ups

Details are in doc 13 under "Known gaps and follow-ups".

- [ ] Check the Windows and macOS CI runs from the first push to `main`, and fix anything case- or path-length related. Check the SQLite version on each runner supports JSON functions (`json_each`) and partial indexes.
- [ ] Add `create` and `recover` commands to the command line.
- [ ] Let the `--newest` option choose its grouping keys (`within=`).
- [ ] Decide how a filesystem walk handles a permission error.
- [ ] An import tool that loads a directory tree into SQLite needs to create parent rows too.
