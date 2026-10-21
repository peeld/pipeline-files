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
