"""Links: where each entity type lives, which copy is the truth, and how the others follow it (decision 0012)."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ConfigError

ROLES = ("authority", "active", "passive")
CLASH_RULES = ("fail", "version_up", "suffix")
OFFLINE_POLICIES = ("fail", "read_only", "hold")
MERGE_TRIGGERS = ("auto", "confirm")
# A holding age limit: a whole number of days, hours or minutes, such as 7d.
DURATION = re.compile(r"([1-9][0-9]*)([dhm])")
_UNITS = {"d": "days", "h": "hours", "m": "minutes"}
LINK_NAME = re.compile(r"[A-Za-z0-9_.-]+")
EVENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# The settings each role accepts, beside its role.
_ROLE_PROPERTIES = {
    "authority": {"offline", "clash", "merge", "max_age"},
    "active": {"order", "rollback", "clash"},
    "passive": {"triggers", "clash"},
}


@dataclass(frozen=True)
class Link:
    """One place an entity type lives, and the policy for keeping it in step with the authority.

    A link names a store, which a tool binds to a real backend at run time.
    """

    name: str
    role: str
    # Position among the active links; None for the authority, passive links and a lone active link.
    order: int | None = None
    # Whether a failure of this active link undoes the whole write.
    rollback: bool = False
    clash: str = "fail"
    # Events that run a passive link. Empty means only an explicit call runs it.
    triggers: tuple[str, ...] = ()
    # What writes do when the authority is unreachable. Set on the authority only.
    offline: str | None = None
    # Whether held work merges without a person confirming it (decision 0015). Set on the authority only.
    merge: str | None = None
    # How long held work may wait before a person must confirm its merge. None means no limit.
    max_age: dt.timedelta | None = None


@dataclass(frozen=True)
class Links:
    """A rule's authority, its active links in order, and its passive links."""

    # The rule that declared these links; a child rule without its own inherits its parent's.
    declared_by: str
    authority: Link
    active: tuple[Link, ...]
    passive: tuple[Link, ...]

    def __iter__(self):
        return iter((self.authority, *self.active, *self.passive))

    @classmethod
    def from_config(cls, rule: str, spec: Any) -> Links:
        context = f"links for rule {rule!r}"
        if not isinstance(spec, Mapping) or not spec:
            raise ConfigError(f"{context}: must be a non-empty mapping of link name to settings")
        links = [_link(rule, name, settings) for name, settings in spec.items()]

        authorities = [link.name for link in links if link.role == "authority"]
        if len(authorities) != 1:
            raise ConfigError(f"{context}: needs exactly one authority, found {authorities or 'none'}")

        active = [link for link in links if link.role == "active"]
        if len(active) > 1:
            unordered = [link.name for link in active if link.order is None]
            if unordered:
                raise ConfigError(f"{context}: active links {unordered} need an order, as there are several")
            orders = [link.order for link in active]
            repeated = sorted({o for o in orders if orders.count(o) > 1})
            if repeated:
                raise ConfigError(f"{context}: active links share order {repeated}")
            active.sort(key=lambda link: link.order)

        return cls(
            declared_by=rule,
            authority=next(link for link in links if link.role == "authority"),
            active=tuple(active),
            passive=tuple(link for link in links if link.role == "passive"),
        )


def _link(rule: str, name: Any, settings: Any) -> Link:
    context = f"rule {rule!r} link {name!r}"
    if not isinstance(name, str) or not LINK_NAME.fullmatch(name):
        raise ConfigError(f"{context}: link names may contain only letters, digits, '_', '.' and '-'")
    if not isinstance(settings, Mapping):
        raise ConfigError(f"{context}: settings must be a mapping with at least a role")
    role = settings.get("role")
    if role not in ROLES:
        raise ConfigError(f"{context}: role must be one of {', '.join(ROLES)}, got {role!r}")
    unknown = set(settings) - {"role"} - _ROLE_PROPERTIES[role]
    if unknown:
        allowed = sorted(_ROLE_PROPERTIES[role])
        article = "an" if role[0] in "aeiou" else "a"
        raise ConfigError(f"{context}: {sorted(unknown)} cannot be set on {article} {role} link; it takes {allowed}")

    clash = settings.get("clash", "fail")
    if clash not in CLASH_RULES:
        raise ConfigError(f"{context}: clash must be one of {', '.join(CLASH_RULES)}, got {clash!r}")

    order = settings.get("order")
    if order is not None and (not isinstance(order, int) or isinstance(order, bool)):
        raise ConfigError(f"{context}: order must be an integer, got {order!r}")

    rollback = settings.get("rollback", True)
    if not isinstance(rollback, bool):
        raise ConfigError(f"{context}: rollback must be true or false, got {rollback!r}")

    triggers = settings.get("triggers", [])
    if not isinstance(triggers, list) or not all(isinstance(t, str) and EVENT_NAME.fullmatch(t) for t in triggers):
        raise ConfigError(f"{context}: triggers must be a list of event names")
    if len(set(triggers)) != len(triggers):
        raise ConfigError(f"{context}: triggers {triggers} list an event more than once")

    offline = settings.get("offline", "fail")
    if offline not in OFFLINE_POLICIES:
        raise ConfigError(f"{context}: offline must be one of {', '.join(OFFLINE_POLICIES)}, got {offline!r}")

    merge = settings.get("merge", "auto")
    if merge not in MERGE_TRIGGERS:
        raise ConfigError(f"{context}: merge must be one of {', '.join(MERGE_TRIGGERS)}, got {merge!r}")
    max_age = settings.get("max_age")
    if max_age is not None:
        found = DURATION.fullmatch(max_age) if isinstance(max_age, str) else None
        if found is None:
            raise ConfigError(f"{context}: max_age must be a whole number of days, hours or minutes, such as '7d'")
        max_age = dt.timedelta(**{_UNITS[found[2]]: int(found[1])})
    held = sorted({"merge", "max_age"} & set(settings))
    if held and offline != "hold":
        raise ConfigError(f"{context}: {held} only apply when offline is hold, not {offline!r}")

    return Link(
        name=name,
        role=role,
        order=order,
        rollback=rollback if role == "active" else False,
        clash=clash,
        triggers=tuple(triggers),
        offline=offline if role == "authority" else None,
        merge=merge if role == "authority" else None,
        max_age=max_age,
    )
