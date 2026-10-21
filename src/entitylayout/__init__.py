"""Entity layout: ask for data by what it is, not where it lives."""

from .backends import OPERATIONS, Backend, FilesystemBackend
from .check import Problem, check_roots
from .entity import Entity
from .errors import (
    AmbiguousParseError,
    ConfigError,
    InvalidValueError,
    LayoutError,
    MissingKeyError,
    NoMatchError,
    OperationNotSupportedError,
    RootNotMappedError,
)
from .keys import Key
from .layout import Layout, Match, Rule, load_config, load_config_data, read_config
from .location import Location
from .query import EntitySequence, Query, collapse_sequence, group_by, newest, sort_by, where
from .roots import Root
from .template import Template

__all__ = [
    "OPERATIONS",
    "AmbiguousParseError",
    "Backend",
    "Entity",
    "EntitySequence",
    "FilesystemBackend",
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
