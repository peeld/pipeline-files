"""Exceptions raised by the layout layer."""

from __future__ import annotations


class LayoutError(Exception):
    """Base class for every error raised by this package."""


class ConfigError(LayoutError):
    """The configuration is malformed or inconsistent."""


class InvalidValueError(LayoutError, ValueError):
    """A key value has the wrong type or breaks its key's constraints."""


class MissingKeyError(LayoutError, KeyError):
    """A key needed to build a location was not supplied and has no default."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


class NoMatchError(LayoutError):
    """A location does not match the rule, or any rule, it was parsed against."""


class AmbiguousParseError(LayoutError):
    """A location can be split into fields in more than one way."""


class RootNotMappedError(LayoutError):
    """A logical root has no real location on this machine."""
