"""
Data models and utilities for the Spack-inspired package dependency resolver.

Provides Version/VersionRange arithmetic, package repository loading,
spec string parsing, and data classes for resolved dependency DAGs.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple


class Version:
    """A concrete software version (e.g., 1.2.3).

    Versions are compared component-wise as integer tuples.
    """

    __slots__ = ('_components', '_string')

    def __init__(self, version_str: str):
        self._string = version_str.strip()
        self._components = tuple(int(x) for x in self._string.split('.'))

    @property
    def components(self) -> Tuple[int, ...]:
        return self._components

    def __eq__(self, other):
        if isinstance(other, Version):
            return self._components == other._components
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, Version):
            return self._components != other._components
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, Version):
            return self._components < other._components
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, Version):
            return self._components <= other._components
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, Version):
            return self._components > other._components
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, Version):
            return self._components >= other._components
        return NotImplemented

    def __hash__(self):
        return hash(self._components)

    def __repr__(self):
        return f"Version('{self._string}')"

    def __str__(self):
        return self._string


class VersionRange:
    """A version range with optional lower and upper bounds.

    Examples:
        VersionRange(Version("1.0"), Version("2.0"))  ->  [1.0, 2.0]
        VersionRange(Version("1.0"), None)             ->  [1.0, inf)
        VersionRange(None, Version("2.0"))             ->  (-inf, 2.0]
        VersionRange(None, None)                       ->  (-inf, inf)
    """

    def __init__(self, lo: Optional[Version] = None, hi: Optional[Version] = None):
        self.lo = lo
        self.hi = hi
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"Invalid version range: {lo} > {hi}")

    def contains(self, version: Version) -> bool:
        """Check if a concrete version falls within this range."""
        if self.lo is not None and version < self.lo:
            return False
        if self.hi is not None and version > self.hi:
            return False
        return True

    def intersect(self, other: 'VersionRange') -> Optional['VersionRange']:
        """Compute the intersection of two version ranges.

        Returns None if the intersection is empty.
        """
        new_lo = self.lo
        if other.lo is not None:
            if new_lo is None or other.lo > new_lo:
                new_lo = other.lo

        new_hi = self.hi
        if other.hi is not None:
            if new_hi is None or other.hi < new_hi:
                new_hi = other.hi

        if new_lo is not None and new_hi is not None and new_lo > new_hi:
            return None

        return VersionRange(new_lo, new_hi)

    def is_exact(self) -> bool:
        """Check if this range specifies exactly one version."""
        return self.lo is not None and self.hi is not None and self.lo == self.hi

    def __repr__(self):
        lo_str = str(self.lo) if self.lo else ''
        hi_str = str(self.hi) if self.hi else ''
        if self.lo == self.hi and self.lo is not None:
            return f"VersionRange('{lo_str}')"
        return f"VersionRange('{lo_str}:{hi_str}')"

    def __eq__(self, other):
        if isinstance(other, VersionRange):
            return self.lo == other.lo and self.hi == other.hi
        return NotImplemented


def parse_version_range(s: str) -> VersionRange:
    """Parse a version range string.

    Formats:
      '1.2.3'        -> exact version [1.2.3, 1.2.3]
      '1.2.3:'       -> lower bound   [1.2.3, inf)
      ':2.0.0'       -> upper bound   (-inf, 2.0.0]
      '1.0.0:2.0.0'  -> closed range  [1.0.0, 2.0.0]
    """
    s = s.strip()
    if s.startswith('@'):
        s = s[1:]

    if ':' in s:
        parts = s.split(':', 1)
        lo = Version(parts[0]) if parts[0].strip() else None
        hi = Version(parts[1]) if parts[1].strip() else None
        return VersionRange(lo, hi)
    else:
        v = Version(s)
        return VersionRange(v, v)


@dataclass
class DependencyDef:
    """A dependency declaration from a package definition."""
    name: str
    version_range: Optional[VersionRange]
    condition: Optional[str]  # "+var", "~var", or "@version_range"
    required_variants: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConflictDef:
    """A conflict declaration from a package definition."""
    version_range: Optional[VersionRange]
    variants: Dict[str, Any]
    message: str


@dataclass
class PackageDef:
    """Package definition from the repository."""
    name: str
    versions: List[Version]
    variants: Dict[str, dict]
    dependencies: List[DependencyDef]
    conflicts: List[ConflictDef]
    provides: List[str]


@dataclass
class ConcreteSpec:
    """A fully resolved package specification."""
    name: str
    version: Version
    variants: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedDAG:
    """The result of dependency resolution.

    Attributes:
        specs: mapping from package name to its ConcreteSpec
        edges: list of (parent_name, child_name) tuples representing
               dependency edges (parent depends on child)
        build_order: topological ordering where every package appears
                     after all of its dependencies
    """
    specs: Dict[str, ConcreteSpec] = field(default_factory=dict)
    edges: List[Tuple[str, str]] = field(default_factory=list)
    build_order: List[str] = field(default_factory=list)


class UnsatisfiableSpecError(Exception):
    """Raised when no valid resolution exists for the given constraints."""
    pass


class ConflictError(Exception):
    """Raised when a package conflict condition is triggered."""
    pass


class PackageRepo:
    """Package repository loaded from a JSON definition file."""

    def __init__(self, path: str):
        with open(path) as f:
            data = json.load(f)

        self.virtuals: Dict[str, List[str]] = data.get('virtuals', {})
        self.packages: Dict[str, PackageDef] = {}

        for name, pkg_data in data.get('packages', {}).items():
            versions = sorted([Version(v) for v in pkg_data['versions']])

            deps = []
            for d in pkg_data.get('dependencies', []):
                vr = parse_version_range(d['version_range']) if d.get('version_range') else None
                rv = d.get('required_variants', {})
                deps.append(DependencyDef(
                    name=d['name'],
                    version_range=vr,
                    condition=d.get('condition'),
                    required_variants=rv,
                ))

            conflicts = []
            for c in pkg_data.get('conflicts', []):
                vr = parse_version_range(c['version_range']) if c.get('version_range') else None
                conflicts.append(ConflictDef(
                    version_range=vr,
                    variants=c.get('variants', {}),
                    message=c.get('message', 'Unknown conflict'),
                ))

            self.packages[name] = PackageDef(
                name=name,
                versions=versions,
                variants=pkg_data.get('variants', {}),
                dependencies=deps,
                conflicts=conflicts,
                provides=pkg_data.get('provides', []),
            )

    def is_virtual(self, name: str) -> bool:
        """Check if a name refers to a virtual package."""
        return name in self.virtuals

    def get_providers(self, virtual: str) -> List[str]:
        """Get the ordered list of concrete providers for a virtual."""
        return self.virtuals.get(virtual, [])

    def get_package(self, name: str) -> PackageDef:
        """Look up a concrete package definition."""
        if name not in self.packages:
            raise UnsatisfiableSpecError(f"Unknown package: {name}")
        return self.packages[name]


def parse_spec(spec_str: str) -> dict:
    """Parse a spec string into its components.

    Format: name[@version_range] [+var] [~var] [key=value] [^dep_spec ...]

    Returns a dict:
      name             - package name (str)
      version_range    - VersionRange or None
      variants         - dict of variant_name -> value
      dep_constraints  - dict of dep_name -> parsed sub-spec dict
    """
    spec_str = spec_str.strip()
    result: dict = {
        'name': None,
        'version_range': None,
        'variants': {},
        'dep_constraints': {},
    }

    # Split on dependency markers (whitespace + ^)
    parts = re.split(r'\s+\^', spec_str)
    main_part = parts[0]
    dep_parts = parts[1:] if len(parts) > 1 else []

    # --- Parse main part ---
    tokens = main_part.split()
    if not tokens:
        raise ValueError("Empty spec string")

    first = tokens[0]
    if '@' in first:
        at_idx = first.index('@')
        result['name'] = first[:at_idx]
        result['version_range'] = parse_version_range(first[at_idx + 1:])
    else:
        result['name'] = first

    for token in tokens[1:]:
        if token.startswith('+'):
            result['variants'][token[1:]] = True
        elif token.startswith('~'):
            result['variants'][token[1:]] = False
        elif '=' in token:
            key, value = token.split('=', 1)
            # Try to parse boolean-like strings
            if value.lower() == 'true':
                result['variants'][key] = True
            elif value.lower() == 'false':
                result['variants'][key] = False
            else:
                result['variants'][key] = value
        else:
            raise ValueError(f"Unexpected token in spec: {token}")

    # --- Parse dependency constraints ---
    for dep_str in dep_parts:
        dep_parsed = parse_spec(dep_str)
        result['dep_constraints'][dep_parsed['name']] = dep_parsed

    return result
