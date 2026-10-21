"""Roots: logical storage bases, mapped to a real location per machine."""

from __future__ import annotations

import fnmatch
import socket
import sys
from collections.abc import Mapping
from typing import Any

from .errors import ConfigError, RootNotMappedError

PLATFORMS = ("linux", "windows", "darwin")
ROOT_PROPERTIES = {"default", "platforms", "hosts"}


def current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def current_host() -> str:
    return socket.gethostname()


class Root:
    """One logical root and the real location it maps to on each machine.

    Lookup order is: the first matching host pattern, then the platform,
    then the default.
    """

    def __init__(
        self,
        name: str,
        *,
        default: str | None = None,
        platforms: Mapping[str, str] | None = None,
        hosts: Mapping[str, str] | None = None,
    ) -> None:
        self.name = name
        self.default = default
        self.platforms = dict(platforms or {})
        self.hosts = dict(hosts or {})
        unknown = set(self.platforms) - set(PLATFORMS)
        if unknown:
            raise ConfigError(f"root {name!r}: unknown platforms {sorted(unknown)}; use {', '.join(PLATFORMS)}")
        for where, value in [("default", default), *self.platforms.items(), *self.hosts.items()]:
            if value is not None and (not isinstance(value, str) or not value):
                raise ConfigError(f"root {name!r}: location for {where!r} must be a non-empty string")
        if default is None and not self.platforms and not self.hosts:
            raise ConfigError(f"root {name!r}: give at least one of default, platforms or hosts")

    @classmethod
    def from_config(cls, name: str, spec: Any) -> Root:
        if isinstance(spec, str):
            return cls(name, default=spec)
        if not isinstance(spec, Mapping):
            raise ConfigError(f"root {name!r}: definition must be a string or a mapping")
        unknown = set(spec) - ROOT_PROPERTIES
        if unknown:
            raise ConfigError(f"root {name!r}: unknown properties {sorted(unknown)}")
        return cls(name, **spec)

    def __repr__(self) -> str:
        return f"Root({self.name!r})"

    def resolve(self, *, platform: str | None = None, host: str | None = None) -> str:
        """Return the real location of this root on the given (or current) machine."""
        host = current_host() if host is None else host
        for pattern, location in self.hosts.items():
            if fnmatch.fnmatchcase(host, pattern):
                return location
        platform = current_platform() if platform is None else platform
        if platform in self.platforms:
            return self.platforms[platform]
        if self.default is not None:
            return self.default
        raise RootNotMappedError(f"root {self.name!r} has no location for host {host!r} on {platform}")
