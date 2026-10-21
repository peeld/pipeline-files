"""Entity layout: ask for data by what it is, not where it lives."""

from .backends import (
    AUTHORITY_OPERATIONS,
    CAPABILITIES,
    LINK_OPERATIONS,
    OPERATIONS,
    AttributeValidator,
    Backend,
    FilesystemBackend,
    SQLiteBackend,
)
from .check import Problem, check_roots
from .engine import Engine
from .entity import Entity
from .errors import (
    AmbiguousParseError,
    ClashError,
    ConfigError,
    EntityExistsError,
    InvalidValueError,
    LayoutError,
    MissingKeyError,
    NoMatchError,
    OperationNotSupportedError,
    OutOfSyncError,
    ReadOnlyError,
    RootNotMappedError,
    UndoError,
    UnreachableError,
    WriteError,
    WriteIncompleteError,
    WriteRolledBackError,
)
from .keys import Key
from .layout import Layout, Match, Rule, load_config, load_config_data, read_config
from .links import Link, Links
from .location import Location
from .query import EntitySequence, Query, collapse_sequence, group_by, newest, sort_by, where
from .records import STATES, VISIBLE_STATES, Record, Sidecar, Step, read_sidecar
from .roots import Root
from .template import Template
from .validation import TypedAttributes

__all__ = [
    "AUTHORITY_OPERATIONS",
    "CAPABILITIES",
    "LINK_OPERATIONS",
    "OPERATIONS",
    "STATES",
    "VISIBLE_STATES",
    "ClashError",
    "Engine",
    "Link",
    "Links",
    "OutOfSyncError",
    "ReadOnlyError",
    "Record",
    "Sidecar",
    "Step",
    "UndoError",
    "UnreachableError",
    "WriteError",
    "WriteIncompleteError",
    "WriteRolledBackError",
    "read_sidecar",
    "AmbiguousParseError",
    "AttributeValidator",
    "Backend",
    "Entity",
    "EntitySequence",
    "EntityExistsError",
    "FilesystemBackend",
    "SQLiteBackend",
    "TypedAttributes",
    "OperationNotSupportedError",
    "Query",
    "collapse_sequence",
    "group_by",
    "newest",
    "sort_by",
    "where",
    "ConfigError",
    "InvalidValueError",
    "Key",
    "Layout",
    "LayoutError",
    "Location",
    "Match",
    "MissingKeyError",
    "NoMatchError",
    "Problem",
    "Root",
    "RootNotMappedError",
    "Rule",
    "Template",
    "check_roots",
    "load_config",
    "load_config_data",
    "read_config",
]
