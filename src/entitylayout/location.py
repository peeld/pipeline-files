"""Locations: where an entity lives on one backend, without any real path."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

from .errors import LayoutError

BACKEND_NAME = re.compile(r"[a-z][a-z0-9+.-]*")
ROOT_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_URI = re.compile(r"(?P<backend>[a-z][a-z0-9+.-]*)://(?P<root>[A-Za-z0-9_.-]+)(?:/(?P<path>.*))?", re.DOTALL)


@dataclass(frozen=True)
class Location:
    """A backend name, a logical root and a relative location under it.

    Written as a URI, ``<backend>://<root>/<path>``, with the path
    percent-encoded. Turning a location into a real path is a separate step,
    because the real path depends on the machine.
    """

    backend: str
    root: str
    path: str

    def __str__(self) -> str:
        return self.uri

    @property
    def uri(self) -> str:
        return f"{self.backend}://{self.root}/{quote(self.path, safe='/')}"

    @classmethod
    def from_uri(cls, uri: str) -> Location:
        match = _URI.fullmatch(uri)
        if not match:
            raise LayoutError(f"{uri!r} is not a location URI of the form backend://root/path")
        return cls(match["backend"], match["root"], unquote(match["path"] or ""))
