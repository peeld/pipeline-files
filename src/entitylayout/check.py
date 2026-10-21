"""The validation pass: check that a layout's directories exist on this machine.

Resolution never touches storage. This pass is the one place that looks at
the real filesystem, and it only reports; it never creates anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import RootNotMappedError
from .layout import Layout


@dataclass(frozen=True)
class Problem:
    root: str
    message: str

    def __str__(self) -> str:
        return f"root {self.root!r}: {self.message}"


def check_roots(layout: Layout, *, platform: str | None = None, host: str | None = None) -> list[Problem]:
    """Report every root that is unmapped, missing or not a directory here."""
    problems = []
    for name, root in layout.roots.items():
        try:
            location = Path(root.resolve(platform=platform, host=host))
        except RootNotMappedError as exc:
            problems.append(Problem(name, str(exc)))
            continue
        if not location.exists():
            problems.append(Problem(name, f"{str(location)!r} does not exist"))
        elif not location.is_dir():
            problems.append(Problem(name, f"{str(location)!r} is not a directory"))
    return problems
