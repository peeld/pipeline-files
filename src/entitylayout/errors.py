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


class OperationNotSupportedError(LayoutError, NotImplementedError):
    """The backend does not implement the operation that was attempted."""


class EntityExistsError(LayoutError):
    """An entity was created where one already exists."""


class NoRecordError(LayoutError):
    """An authority has no record with the internal ID asked for."""


class RecordExistsError(LayoutError):
    """A record that has not failed already has the internal ID being reserved. ``record`` is that record."""

    def __init__(self, message: str, record=None) -> None:
        super().__init__(message)
        self.record = record


class HoldingError(LayoutError):
    """The holding area, or an element in it, cannot be used as asked."""


class UnreachableError(LayoutError):
    """A backend cannot reach the place its data lives, such as a database server that is down."""


class ClashError(LayoutError):
    """Something else already holds a location, such as a file with different content."""


class UndoError(LayoutError):
    """A link step cannot be undone without removing something it did not create."""


class WriteError(LayoutError):
    """A write did not commit. ``record`` is the authority's record as the write left it, if one was reserved."""

    def __init__(self, message: str, record=None) -> None:
        super().__init__(message)
        self.record = record


class WriteRolledBackError(WriteError):
    """A write failed and was undone. Its record is marked failed."""


class OutOfSyncError(WriteError):
    """A write was kept in the authority, but an active link is behind and needs a retry."""


class WriteIncompleteError(WriteError):
    """A write stopped with its record still pending. Recovery finishes or undoes it from the operation log."""


class ReadOnlyError(WriteError):
    """The authority is unreachable and the offline policy allows reads only."""
