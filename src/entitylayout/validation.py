"""The optional attribute validation layer.

The core never checks attributes (decision 0005). A deployment that wants
them checked passes a validator to a backend, which calls it before every
write. ``TypedAttributes`` is a simple one that checks the types a rule
declares.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from .errors import InvalidValueError
from .layout import Rule


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


ATTRIBUTE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "int": _is_int,
    "float": lambda v: isinstance(v, float) or _is_int(v),
    "bool": lambda v: isinstance(v, bool),
    "date": lambda v: isinstance(v, dt.date) and not isinstance(v, dt.datetime),
    "datetime": lambda v: isinstance(v, dt.datetime),
    "list": lambda v: isinstance(v, (list, tuple)),
    "map": lambda v: isinstance(v, Mapping),
}


class TypedAttributes:
    """Checks attributes against the types their rule declares.

    Attributes the rule does not declare are refused unless allow_undeclared
    is true. None is accepted for any declared attribute, meaning "not set".
    """

    def __init__(self, *, allow_undeclared: bool = False) -> None:
        self.allow_undeclared = allow_undeclared

    def __call__(self, rule: Rule, attributes: Mapping[str, Any]) -> None:
        for name, value in attributes.items():
            declared = rule.attributes.get(name)
            if declared is None:
                if not self.allow_undeclared:
                    raise InvalidValueError(f"rule {rule.name!r}: attribute {name!r} is not declared")
                continue
            if value is not None and not ATTRIBUTE_CHECKS[declared](value):
                raise InvalidValueError(f"rule {rule.name!r}: attribute {name!r} must be a {declared}, got {value!r}")
