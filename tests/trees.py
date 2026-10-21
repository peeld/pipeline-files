"""Build real directory trees of entities for the query gates."""

from __future__ import annotations

from entitylayout import Layout
from entitylayout.keys import nfc


def make_tree(layout: Layout, rule: str, entities: list[dict]) -> dict[str, dict]:
    """Create each entity as a directory under its root, returning fields by location path.

    Duplicates collapse to one entity. Paths with any level that differs from
    an earlier one only by case are skipped, because the two would share a
    directory on Windows and macOS.
    """
    created: dict[str, dict] = {}
    spelled: dict[str, str] = {}
    for fields in entities:
        location = layout.locate(rule, fields)
        parts = location.path.split("/")
        prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        if any(spelled.get(nfc(p).casefold(), p) != p for p in prefixes):
            continue
        spelled.update((nfc(p).casefold(), p) for p in prefixes)
        layout.real_path(location).mkdir(parents=True, exist_ok=True)
        created[location.path] = fields
    return created
