"""Command line: check a layout, and resolve in both directions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .backends import Backend, FilesystemBackend, SQLiteBackend
from .check import check_roots
from .errors import LayoutError
from .layout import Layout, load_config
from .location import Location
from .query import EntitySequence, Query, collapse_sequence, newest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="entitylayout", description=__doc__)
    parser.add_argument("config", help="config file, or directory of config files")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("check", help="load the config and check every root exists on this machine")

    locate = commands.add_parser("locate", help="fields to location")
    locate.add_argument("rule")
    locate.add_argument("fields", nargs="*", metavar="key=value")
    locate.add_argument("--backend", default="fs")
    locate.add_argument("--path", action="store_true", help="print the real path instead of the URI")

    parse = commands.add_parser("parse", help="location URI or real path to rule and fields")
    parse.add_argument("location")
    parse.add_argument("--rule")
    parse.add_argument("--backend", default="fs", help="backend for a real path (default fs)")

    query = commands.add_parser("query", help="partial fields to every matching entity, one JSON object per line")
    query.add_argument("rule")
    query.add_argument("fields", nargs="*", metavar="key=value")
    query.add_argument("--newest", metavar="KEY", help="keep only the highest KEY in each group, such as version")
    query.add_argument("--collapse", metavar="KEY", help="collapse a numbered KEY, such as frame, into ranges")
    query.add_argument("--path", action="store_true", help="print real paths instead of JSON")
    query.add_argument("--db", metavar="PATH", help="query an SQLite database instead of the filesystem")
    query.add_argument("--template", default="fs", help="template the backend addresses entities by (default fs)")
    query.add_argument(
        "--attr",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="keep entities whose attribute equals VALUE, read as the attribute's declared type (needs --db)",
    )

    args = parser.parse_args(argv)
    try:
        layout = load_config(args.config)
        if args.command == "check":
            return _check(layout)
        if args.command == "locate":
            return _locate(layout, args)
        if args.command == "query":
            return _query(layout, args)
        return _parse(layout, args)
    except LayoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _check(layout: Layout) -> int:
    problems = check_roots(layout)
    for problem in problems:
        print(problem)
    if not problems:
        print(f"ok: version {layout.version}, {len(layout.rules)} rules, {len(layout.roots)} roots")
    return 1 if problems else 0


def _fields(layout: Layout, rule_name: str, items: Sequence[str]) -> dict[str, Any]:
    rule = layout.rule(rule_name)
    fields: dict[str, Any] = {}
    for item in items:
        name, sep, raw = item.partition("=")
        if not sep:
            raise LayoutError(f"expected key=value, got {item!r}")
        if name not in rule.keys:
            raise LayoutError(f"rule {rule.name!r} has no key {name!r}; its keys are {list(rule.keys)}")
        fields[name] = layout.keys[name].coerce(raw)
    return fields


def _locate(layout: Layout, args: argparse.Namespace) -> int:
    location = layout.locate(args.rule, _fields(layout, args.rule, args.fields), args.backend)
    print(layout.real_path(location) if args.path else location.uri)
    return 0


def _query(layout: Layout, args: argparse.Namespace) -> int:
    attributes = _attributes(layout, args.rule, args.attr)
    query = Query(args.rule, _fields(layout, args.rule, args.fields), attributes or None)
    if args.newest:
        query = query.then(newest(args.newest))
    if args.collapse:
        query = query.then(collapse_sequence(args.collapse))
    backend: Backend
    if args.db:
        # Connecting would create a missing file, and an empty database would quietly answer nothing.
        if not Path(args.db).is_file():
            raise LayoutError(f"no SQLite database at {args.db!r}")
        backend = SQLiteBackend(layout, args.db, args.template)
    else:
        backend = FilesystemBackend(layout, args.template)
    for result in query.run(backend):
        if isinstance(result, EntitySequence):
            location = result.entities[0].location
            record = {"rule": result.rule, "fields": result.fields, result.key: str(result)}
        else:
            location = result.location
            record = {"rule": result.rule, "fields": result.fields, "location": location.uri}
            if result.attributes:
                record["attributes"] = result.attributes
        if args.path:
            suffix = f"  [{result.key} {result}]" if isinstance(result, EntitySequence) else ""
            print(f"{layout.real_path(location)}{suffix}")
        else:
            print(json.dumps(record, default=_json_default, ensure_ascii=False))
    return 0


def _attributes(layout: Layout, rule_name: str, items: Sequence[str]) -> dict[str, Any]:
    """Attribute filters from NAME=VALUE text. Undeclared attributes are compared as text."""
    rule = layout.rule(rule_name)
    attributes: dict[str, Any] = {}
    for item in items:
        name, sep, raw = item.partition("=")
        if not sep:
            raise LayoutError(f"expected NAME=VALUE for --attr, got {item!r}")
        kind = rule.attributes.get(name, "string")
        try:
            attributes[name] = _ATTRIBUTE_PARSERS[kind](raw)
        except KeyError:
            raise LayoutError(f"attribute {name!r} is a {kind}, which --attr cannot compare") from None
        except ValueError:
            raise LayoutError(f"attribute {name!r}: {raw!r} is not a {kind}") from None
    return attributes


def _bool(raw: str) -> bool:
    if raw not in ("true", "false"):
        raise ValueError(raw)
    return raw == "true"


_ATTRIBUTE_PARSERS = {
    "string": str,
    "int": int,
    "float": float,
    "bool": _bool,
    "date": dt.date.fromisoformat,
    "datetime": dt.datetime.fromisoformat,
}


def _parse(layout: Layout, args: argparse.Namespace) -> int:
    if "://" in args.location:
        location = Location.from_uri(args.location)
    else:
        location = layout.location_for_path(args.location, args.backend)
    match = layout.parse(location, args.rule)
    print(json.dumps({"rule": match.rule, "fields": match.fields}, default=_json_default, ensure_ascii=False))
    return 0


def _json_default(value: Any) -> Any:
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(f"cannot serialize {value!r}")


if __name__ == "__main__":
    sys.exit(main())
