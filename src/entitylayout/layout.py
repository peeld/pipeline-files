"""The layout: keys, rules and roots loaded from configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .errors import AmbiguousParseError, ConfigError, LayoutError, NoMatchError
from .keys import Key
from .location import BACKEND_NAME, ROOT_NAME, Location
from .roots import Root
from .template import Template

SECTIONS = {"version", "keys", "rules", "roots", "links"}
RULE_PROPERTIES = {"parent", "keys", "root", "templates", "attributes", "description"}
ATTRIBUTE_TYPES = ("string", "int", "float", "bool", "date", "datetime", "list", "map")
CONFIG_SUFFIXES = (".yaml", ".yml", ".json")


@dataclass(frozen=True)
class Match:
    """A location read back into a rule and its fields."""

    rule: str
    fields: dict[str, Any]


class Rule:
    """A named entity type: its keys, its root and a template per backend.

    A rule with a parent inherits the parent's keys, root and attributes, and
    each of its templates continues the parent's template for that backend.
    """

    def __init__(
        self,
        name: str,
        *,
        keys: tuple[str, ...],
        root: str,
        templates: Mapping[str, Template],
        attributes: Mapping[str, str],
        parent: str | None = None,
        description: str | None = None,
    ) -> None:
        self.name = name
        self.keys = keys
        self.root = root
        self.templates = dict(templates)
        self.attributes = dict(attributes)
        self.parent = parent
        self.description = description

    def __repr__(self) -> str:
        return f"Rule({self.name!r})"

    def template(self, backend: str) -> Template:
        try:
            return self.templates[backend]
        except KeyError:
            raise LayoutError(f"rule {self.name!r} has no template for backend {backend!r}") from None


class Layout:
    """A loaded configuration, ready to resolve in both directions."""

    def __init__(
        self,
        version: Any,
        keys: Mapping[str, Key],
        rules: Mapping[str, Rule],
        roots: Mapping[str, Root],
        links: Mapping[str, Any] | None = None,
    ) -> None:
        self.version = version
        self.keys = dict(keys)
        self.rules = dict(rules)
        self.roots = dict(roots)
        # Links are kept as written until the authority and link engine reads them.
        self.links = dict(links or {})

    def with_roots(self, locations: Mapping[str, str | os.PathLike]) -> Layout:
        """A copy of this layout with some roots mapped to fixed locations, such as a sandbox."""
        roots = dict(self.roots)
        for name, location in locations.items():
            if name not in roots:
                raise LayoutError(f"no root named {name!r}")
            roots[name] = Root(name, default=str(location))
        return Layout(self.version, self.keys, self.rules, roots, self.links)

    def rule(self, name: str) -> Rule:
        try:
            return self.rules[name]
        except KeyError:
            raise LayoutError(f"no rule named {name!r}") from None

    # Fields to location

    def locate(self, rule: str, fields: Mapping[str, Any], backend: str = "fs") -> Location:
        """Return where the entity named by fields lives on backend."""
        r = self.rule(rule)
        unknown = set(fields) - set(r.keys)
        if unknown:
            raise LayoutError(f"rule {rule!r} has no keys {sorted(unknown)}")
        return Location(backend, r.root, r.template(backend).format(fields))

    # Location to fields

    def parse(self, location: Location | str, rule: str | None = None) -> Match:
        """Read a location back into its rule and fields.

        With no rule given, every rule on the location's backend and root is
        tried, and the location must match exactly one of them.
        """
        matches = self.matches(location, rule)
        if not matches:
            raise NoMatchError(f"{_uri(location)} does not match {'rule ' + repr(rule) if rule else 'any rule'}")
        if len(matches) > 1:
            names = [m.rule for m in matches]
            raise AmbiguousParseError(f"{_uri(location)} matches several rules: {names}")
        return matches[0]

    def matches(self, location: Location | str, rule: str | None = None) -> list[Match]:
        """Every rule a location can be read as, with its fields."""
        if isinstance(location, str):
            location = Location.from_uri(location)
        candidates = [self.rule(rule)] if rule else list(self.rules.values())
        found = []
        for r in candidates:
            if r.root != location.root or location.backend not in r.templates:
                if rule:
                    raise NoMatchError(f"{location.uri} is not on rule {rule!r}'s root and backend")
                continue
            try:
                fields = r.templates[location.backend].parse(location.path)
            except NoMatchError:
                continue
            found.append(Match(r.name, fields))
        return found

    # Locations and real paths

    def real_path(self, location: Location, *, platform: str | None = None, host: str | None = None) -> Path:
        """Return the real filesystem path of a location on this (or the given) machine."""
        base = self._root(location.root).resolve(platform=platform, host=host)
        return Path(base).joinpath(*PurePosixPath(location.path).parts)

    def location_for_path(
        self,
        path: str | os.PathLike,
        backend: str = "fs",
        *,
        platform: str | None = None,
        host: str | None = None,
    ) -> Location:
        """Turn a real path back into a location, by finding the root it is under.

        When roots are nested, the deepest root that contains the path wins.
        """
        target = Path(path)
        best: tuple[int, str, PurePosixPath] | None = None
        for name, root in self.roots.items():
            try:
                base = Path(root.resolve(platform=platform, host=host))
                relative = target.relative_to(base)
            except (LayoutError, ValueError):
                continue
            depth = len(base.parts)
            if best is None or depth > best[0]:
                best = (depth, name, PurePosixPath(*relative.parts))
        if best is None:
            raise NoMatchError(f"{str(target)!r} is not under any root on this machine")
        return Location(backend, best[1], str(best[2]) if best[2].parts else "")

    def _root(self, name: str) -> Root:
        try:
            return self.roots[name]
        except KeyError:
            raise LayoutError(f"no root named {name!r}") from None


def _uri(location: Location | str) -> str:
    return location.uri if isinstance(location, Location) else location


# Loading


def load_config(path: str | os.PathLike) -> Layout:
    """Load a layout from a config file, or from every config file in a directory.

    Files are YAML (JSON is accepted, as YAML reads it). Each file holds one
    or more top-level sections: version, keys, rules, roots and links. A
    section may appear in only one file.
    """
    return load_config_data(read_config(path))


def read_config(path: str | os.PathLike) -> dict[str, Any]:
    """Read and merge config files into one mapping of sections, without checking them."""
    path = Path(path)
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix in CONFIG_SUFFIXES and p.is_file())
        if not files:
            raise ConfigError(f"no {', '.join(CONFIG_SUFFIXES)} files in {str(path)!r}")
    else:
        files = [path]
    data: dict[str, Any] = {}
    origin: dict[str, Path] = {}
    for file in files:
        try:
            with open(file, encoding="utf-8") as handle:
                content = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"cannot read {str(file)!r}: {exc}") from None
        if content is None:
            continue
        if not isinstance(content, Mapping):
            raise ConfigError(f"{str(file)!r} must contain a mapping of sections")
        for section, value in content.items():
            if section in data:
                raise ConfigError(f"section {section!r} appears in both {str(origin[section])!r} and {str(file)!r}")
            data[section] = value
            origin[section] = file
    return data


def load_config_data(data: Mapping[str, Any]) -> Layout:
    """Build a layout from already-parsed configuration data."""
    unknown = set(data) - SECTIONS
    if unknown:
        raise ConfigError(f"unknown config sections {sorted(unknown)}; expected {sorted(SECTIONS)}")
    if data.get("version") is None:
        raise ConfigError("config must set a version, recorded on every entity it creates")
    version = data["version"]
    if not isinstance(version, (str, int)) or isinstance(version, bool):
        raise ConfigError("version must be a string or an integer")

    keys = {name: Key.from_config(name, spec) for name, spec in _section(data, "keys").items()}

    roots = {}
    for name, spec in _section(data, "roots").items():
        if not ROOT_NAME.fullmatch(str(name)):
            raise ConfigError(f"root name {name!r} may contain only letters, digits, '_', '.' and '-'")
        roots[name] = Root.from_config(name, spec)

    rule_specs = _section(data, "rules")
    rules: dict[str, Rule] = {}
    for name in rule_specs:
        _build_rule(name, rule_specs, keys, roots, rules, ())

    return Layout(version, keys, rules, roots, _section(data, "links"))


def _section(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"section {name!r} must be a mapping")
    return value


def _build_rule(
    name: str,
    specs: Mapping[str, Any],
    keys: Mapping[str, Key],
    roots: Mapping[str, Root],
    built: dict[str, Rule],
    chain: tuple[str, ...],
) -> Rule:
    if name in built:
        return built[name]
    if name in chain:
        raise ConfigError(f"rule parents form a cycle: {' -> '.join((*chain, name))}")
    spec = specs[name]
    if not isinstance(spec, Mapping):
        raise ConfigError(f"rule {name!r}: definition must be a mapping")
    unknown = set(spec) - RULE_PROPERTIES
    if unknown:
        raise ConfigError(f"rule {name!r}: unknown properties {sorted(unknown)}")

    parent: Rule | None = None
    parent_name = spec.get("parent")
    if parent_name is not None:
        if parent_name not in specs:
            raise ConfigError(f"rule {name!r}: parent {parent_name!r} is not defined")
        parent = _build_rule(parent_name, specs, keys, roots, built, (*chain, name))

    own_keys = spec.get("keys") or []
    if not isinstance(own_keys, list) or not all(isinstance(k, str) for k in own_keys):
        raise ConfigError(f"rule {name!r}: keys must be a list of key names")
    for key in own_keys:
        if key not in keys:
            raise ConfigError(f"rule {name!r}: key {key!r} is not defined")
    rule_keys = (*(parent.keys if parent else ()), *own_keys)
    duplicates = sorted({k for k in rule_keys if rule_keys.count(k) > 1})
    if duplicates:
        raise ConfigError(f"rule {name!r}: keys {duplicates} are listed more than once (including the parent's)")
    if not rule_keys:
        raise ConfigError(f"rule {name!r}: a rule needs at least one key")

    root = spec.get("root")
    if root is None and parent is not None:
        root = parent.root
    elif parent is not None and root != parent.root:
        raise ConfigError(f"rule {name!r}: root {root!r} differs from parent's root {parent.root!r}")
    if root is None:
        raise ConfigError(f"rule {name!r}: needs a root (or a parent to inherit one from)")
    if root not in roots:
        raise ConfigError(f"rule {name!r}: root {root!r} is not defined")

    templates_spec = spec.get("templates") or {}
    if not isinstance(templates_spec, Mapping) or not templates_spec:
        raise ConfigError(f"rule {name!r}: templates must be a non-empty mapping of backend to template")
    templates: dict[str, Template] = {}
    for backend, text in templates_spec.items():
        context = f"rule {name!r} template {backend!r}"
        if not BACKEND_NAME.fullmatch(str(backend)):
            raise ConfigError(f"{context}: backend names are lowercase letters, digits, '+', '.' and '-'")
        if parent is not None:
            if backend not in parent.templates:
                raise ConfigError(f"{context}: parent {parent.name!r} has no {backend!r} template to extend")
            text = f"{parent.templates[backend].text}/{text}"
        template = Template(text, keys, context=context)
        used = template.key_names
        if set(used) != set(rule_keys):
            missing = [k for k in rule_keys if k not in used]
            extra = [k for k in used if k not in rule_keys]
            detail = "; ".join(p for p in (missing and f"missing {missing}", extra and f"not rule keys {extra}") if p)
            raise ConfigError(f"{context}: template must use exactly the rule's keys ({detail})")
        templates[backend] = template
    if parent is not None:
        missing_backends = sorted(set(parent.templates) - set(templates))
        if missing_backends:
            raise ConfigError(f"rule {name!r}: does not extend the parent's templates for {missing_backends}")

    attributes = dict(parent.attributes if parent else {})
    attributes_spec = spec.get("attributes") or {}
    if not isinstance(attributes_spec, Mapping):
        raise ConfigError(f"rule {name!r}: attributes must be a mapping of name to type")
    for attr, attr_type in attributes_spec.items():
        if attr_type not in ATTRIBUTE_TYPES:
            raise ConfigError(f"rule {name!r}: attribute {attr!r} type must be one of {', '.join(ATTRIBUTE_TYPES)}")
        if attr in rule_keys:
            raise ConfigError(f"rule {name!r}: {attr!r} is a key, so it cannot also be an attribute")
        attributes[attr] = attr_type

    rule = Rule(
        name,
        keys=rule_keys,
        root=root,
        templates=templates,
        attributes=attributes,
        parent=parent_name,
        description=spec.get("description"),
    )
    built[name] = rule
    return rule
