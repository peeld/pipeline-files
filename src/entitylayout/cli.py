"""Command line: check a layout, and resolve in both directions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from typing import Any

from .check import check_roots
from .errors import LayoutError
from .layout import Layout, load_config
from .location import Location


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

    args = parser.parse_args(argv)
    try:
        layout = load_config(args.config)
        if args.command == "check":
            return _check(layout)
        if args.command == "locate":
            return _locate(layout, args)
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


def _locate(layout: Layout, args: argparse.Namespace) -> int:
    rule = layout.rule(args.rule)
    fields: dict[str, Any] = {}
    for item in args.fields:
        name, sep, raw = item.partition("=")
        if not sep:
            raise LayoutError(f"expected key=value, got {item!r}")
        if name not in rule.keys:
            raise LayoutError(f"rule {rule.name!r} has no key {name!r}; its keys are {list(rule.keys)}")
        fields[name] = layout.keys[name].coerce(raw)
    location = layout.locate(args.rule, fields, args.backend)
    print(layout.real_path(location) if args.path else location.uri)
    return 0


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
