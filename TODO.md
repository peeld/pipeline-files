# TODO: handoff for the next session

**Last updated:** 2026-10-21. **Next up:** phase 4, authority, active links and rollback.

## Where things stand

- Phases 1 to 3 of the [build order](docs/12-build-order-and-verification.md) are built, and all three gates pass.
- The work is on stacked local branches. None has been pushed and no PR exists. The user chose to keep building locally for now.
  - `phase-1-schema-and-rules`: keys, rules, roots, templates, two-way resolution, CLI, JSON Schema.
  - `phase-2-filesystem-query`, built on phase 1: backend interface, filesystem backend, queries and filters.
  - `phase-3-sqlite-backend`, built on phase 2: SQLite backend, `create`, attribute filters, capability flags, the optional validator, `query --db`. It also holds this file.
- The tests have only run on Python 3.10 on Linux, with SQLite 3.37. `.github/workflows/tests.yml` also covers 3.12 on Linux, Windows and macOS, but has never run.

## Before starting

1. Ask whether to push the branches and open stacked PRs (phase 1 into `main`, phase 2 into phase 1, phase 3 into phase 2), or to keep building locally.
2. Set up and check that everything passes:

   ```sh
   python3 -m venv .venv && .venv/bin/pip install -e ".[test]" -r requirements-docs.txt
   .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
   .venv/bin/pytest
   .venv/bin/mkdocs build --strict
   ```

3. Read [docs/13-implementation-plan.md](docs/13-implementation-plan.md), especially "Design notes for phase 4" and "Known gaps and follow-ups". Then read docs 06 and 07, and decisions 0001 and 0011.

## Phase 4 tasks

- [ ] Define the `links` section (role, order, triggers, rollback, clash rule, offline policy) in the JSON Schema, and read it in `layout.py`. Record the shape as decision 0012.
- [ ] Records with internal ID, state, revision and content hash, and an operation log written in the same transaction. This is SQLite schema version 2, with an upgrade from version 1.
- [ ] Hide pending and failed rows from normal queries.
- [ ] The write flow, as named steps a test can make fail: reserve, realize active links in order, then commit, roll back what was created, or mark out of sync.
- [ ] `create` on the filesystem backend as an idempotent link step, with undo of only what it created.
- [ ] Sidecars stamped with revision and hash, and recovery from the operation log. Decide the sidecar format (doc 13 suggests JSON).
- [ ] Write the phase 4 gate: injected failures at every step leave only the declared record states.
- [ ] Update the docs: tick phase 4 in doc 13, update the status lines in `README.md` and `docs/README.md`, and refresh this file.

## Smaller follow-ups

Details are in doc 13 under "Known gaps and follow-ups".

- [ ] Push and watch the Windows and macOS CI runs, and fix anything case- or path-length related. Check the SQLite version on each runner supports JSON functions (`json_each`).
- [ ] Let the `--newest` option choose its grouping keys (`within=`).
- [ ] Decide how a filesystem walk handles a permission error.
- [ ] An import tool that loads a directory tree into SQLite needs to create parent rows too.
