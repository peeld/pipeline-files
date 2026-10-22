"""A reference migration script: move rules to a new authority, keeping identity, history and links.

Decision 0018 makes migration a site's own script. This is the smallest one
that keeps its three rules, and the phase 6 gate runs it. A site adds its own
steps around it, such as a backup first and a check afterwards.

1. Claim every rule on the old authority. From then on, writes to the rules
   there raise UnreachableError, so each rule's offline policy applies.
2. Restore every record, in any state, with its log, under its own ID in the
   new authority. Link items are not touched.
3. Point tools at the new authority, by editing the configuration or binding
   the authority's link name to the new backend. Then run ``recover()`` and
   ``merge()`` there.

The claims are never released, so a tool still pointed at the old authority
keeps seeing the rules as offline. Run again after a stop, it finishes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from entitylayout import Backend, Layout, LayoutError, Record

CLAIMANT = "migration"


def family(layout: Layout, rule: str) -> list[str]:
    """The rules that share rule's links: the one that declares them, and the children that inherit them."""
    declared_by = layout.rule(rule).links.declared_by
    return [r.name for r in layout.rules.values() if r.links is not None and r.links.declared_by == declared_by]


def migrate(
    old: Backend,
    new: Backend,
    rules: Iterable[str],
    *,
    claimant: str = CLAIMANT,
    checkpoint: Callable[[str], None] = lambda step: None,
) -> list[Record]:
    """Move every record of rules from old to new, and return them as restored."""
    rules = list(rules)
    for rule in rules:
        checkpoint(f"claim_rule:{rule}")
        if not old.claim_rule(rule, claimant):
            raise LayoutError(f"rule {rule!r} is claimed by someone else on {old!r}, so it is not moved")
    moved = []
    for record in old.records(*rules):
        checkpoint(f"restore:{record.rule}")
        moved.append(new.restore(record, old.history(record.id)))
    return moved
