# TODO: handoff for the next session

**Last updated:** 2026-10-21. **Next up:** phase 3, the SQLite backend and attributes.

## Where things stand

- Phases 1 and 2 of the [build order](docs/12-build-order-and-verification.md) are built, and both gates pass (199 tests).
- The work is on stacked local branches. Neither branch has been pushed and no PR exists.
  - `phase-1-schema-and-rules`: keys, rules, roots, templates, two-way resolution, CLI, JSON Schema.
  - `phase-2-filesystem-query`, built on phase 1: backend interface, filesystem backend, queries and filters. It also holds this file.
- The tests have only run on Python 3.10 on Linux. `.github/workflows/tests.yml` also covers 3.12 on Linux, Windows and macOS, but has never run.

## Before starting

1. Ask whether to push the branches and open PRs (phase 1 into `main`, then phase 2 into phase 1), or to keep building locally.
2. Set up and check that everything passes:

   ```sh
   python3 -m venv .venv && .venv/bin/pip install -e ".[test]" -r requirements-docs.txt
   .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
   .venv/bin/pytest
   .venv/bin/mkdocs build --strict
   ```

3. Read [docs/13-implementation-plan.md](docs/13-implementation-plan.md), especially "Design notes for phase 3" and "Known gaps and follow-ups".

## Phase 3 tasks

- [ ] Decide the SQLite table layout and how a database row gets its location. Write decision record 0011 (and add it to `docs/decisions/README.md`, `docs/README.md` and `mkdocs.yml`). The recommendation is in doc 13.
- [ ] Add `src/entitylayout/backends/sqlite.py` with `query`, `exists` and `create`, and export it from `backends/__init__.py` and the package `__init__.py`.
- [ ] Add attribute filters to queries on backends that support them. Add capability flags beside `supported_operations()` in `backends/base.py`.
- [ ] Leave room for an optional attribute validation layer. The core must not validate attributes (decision 0005).
- [ ] Write the phase 3 gate: the same random entities and partial queries on the filesystem and SQLite backends, with identical results. Reuse `tests/strategies.py` and the tree builder in `tests/test_query_gate.py`.
- [ ] Optionally, a `--backend sqlite --db PATH` option for the `query` command.
- [ ] Update the docs: tick phase 3 in doc 13, and describe the database answer in doc 05. Update the status lines in `README.md` and `docs/README.md`, and refresh this file for the following session.

## Smaller follow-ups

Details are in doc 13 under "Known gaps and follow-ups".

- [ ] Push and watch the Windows and macOS CI runs, and fix anything case- or path-length related.
- [ ] Let the `--newest` option choose its grouping keys (`within=`).
- [ ] Decide how a filesystem walk handles a permission error.
