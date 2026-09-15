"""Version constraint parsing and evaluation for Puppet Forge modules."""

import re
from functools import total_ordering


@total_ordering
class SemVer:
    """Semantic version representation."""

    def __init__(self, version_str):
        parts = version_str.strip().split('.')
        self.major = int(parts[0])
        self.minor = int(parts[1]) if len(parts) > 1 else 0
        self.patch = int(parts[2]) if len(parts) > 2 else 0

    def __eq__(self, other):
        if isinstance(other, str):
            other = SemVer(other)
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

    def __lt__(self, other):
        if isinstance(other, str):
            other = SemVer(other)
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def __repr__(self):
        return f"{self.major}.{self.minor}.{self.patch}"

    def __hash__(self):
        return hash((self.major, self.minor, self.patch))


class Constraint:
    """A single version constraint (e.g., '>= 3.0.0')."""

    def __init__(self, op, version):
        self.op = op
        self.version = SemVer(version)

    def satisfied_by(self, version):
        if isinstance(version, str):
            version = SemVer(version)
        if self.op == '>=':
            return version >= self.version
        elif self.op == '<=':
            return version <= self.version
        elif self.op == '>':
            return version > self.version
        elif self.op == '<':
            return version < self.version
        elif self.op == '=':
            return version == self.version
        return False

    def __repr__(self):
        return f"{self.op} {self.version}"


def parse_constraint(constraint_str):
    """Parse a version constraint string into a list of Constraint objects.

    Supports:
    - Bare version: "9.6.0" (exact pin)
    - Comparison: >=, <=, >, <, =
    - Range: ">= 3.0.0 < 5.0.0"
    - Pessimistic: ~> X.Y or ~> X.Y.Z
    """
    constraint_str = constraint_str.strip()

    # Handle bare version string (exact pin)
    if re.match(r'^\d+\.\d+\.\d+$', constraint_str):
        return [Constraint('=', constraint_str)]

    # Handle pessimistic operator
    if constraint_str.startswith('~>'):
        version_str = constraint_str[2:].strip()
        parts = version_str.split('.')

        if len(parts) == 2:
            # ~> X.Y — should be >= X.Y.0 < (X+1).0.0
            lower = f"{parts[0]}.{parts[1]}.0"
            upper = f"{parts[0]}.{int(parts[1]) + 1}.0"
            return [Constraint('>=', lower), Constraint('<', upper)]
        elif len(parts) == 3:
            # ~> X.Y.Z — means >= X.Y.Z < X.(Y+1).0
            lower = version_str
            upper = f"{parts[0]}.{int(parts[1]) + 1}.0"
            return [Constraint('>=', lower), Constraint('<', upper)]

    # Handle range constraints (space-separated operators)
    constraints = []
    tokens = constraint_str.split()
    i = 0
    while i < len(tokens):
        if tokens[i] in ('>=', '<=', '>', '<', '='):
            op = tokens[i]
            version = tokens[i + 1]
            constraints.append(Constraint(op, version))
            i += 2
        else:
            i += 1

    return constraints


def satisfies_all(version, constraints):
    """Check if a version satisfies all constraints in the list."""
    if isinstance(version, str):
        version = SemVer(version)
    return all(c.satisfied_by(version) for c in constraints)
