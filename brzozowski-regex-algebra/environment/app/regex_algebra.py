"""
Extended Regular Expression Algebra

Supports complement (~) and intersection (&) in addition to standard
regular expression operations.

"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Set


# ─── AST Node Classes ───────────────────────────────────────────────

class Regex:
    """Base class for regular expression AST nodes."""
    pass


@dataclass(frozen=True)
class Empty(Regex):
    """The empty set -- matches no strings."""
    pass


@dataclass(frozen=True)
class Epsilon(Regex):
    """The empty string -- matches only the empty string."""
    pass


@dataclass(frozen=True)
class Char(Regex):
    """A single character literal."""
    c: str


@dataclass(frozen=True)
class Alt(Regex):
    """Alternation (union): L(left) | L(right)."""
    left: Regex
    right: Regex


@dataclass(frozen=True)
class Seq(Regex):
    """Concatenation (sequence): L(left) . L(right)."""
    left: Regex
    right: Regex


@dataclass(frozen=True)
class Star(Regex):
    """Kleene star: L(expr)*."""
    expr: Regex


@dataclass(frozen=True)
class Complement(Regex):
    """Complement: all strings over the alphabet NOT in L(expr)."""
    expr: Regex


@dataclass(frozen=True)
class Intersection(Regex):
    """Intersection: L(left) & L(right)."""
    left: Regex
    right: Regex


# ─── Core Operations ────────────────────────────────────────────────

def nullable(r: Regex) -> bool:
    """Return True if the empty string is in L(r)."""
    raise NotImplementedError


def matches(r: Regex, s: str) -> bool:
    """Return True if string s is in L(r)."""
    raise NotImplementedError


def is_empty(r: Regex, alphabet: Set[str]) -> bool:
    """Return True if L(r) = {} over the given alphabet."""
    raise NotImplementedError


def is_universal(r: Regex, alphabet: Set[str]) -> bool:
    """Return True if L(r) equals the set of all strings over the alphabet."""
    raise NotImplementedError


def equivalent(r1: Regex, r2: Regex, alphabet: Set[str]) -> bool:
    """Return True if L(r1) = L(r2) over the given alphabet."""
    raise NotImplementedError


def parse(s: str) -> Regex:
    """Parse a regex string into an AST. See SPEC.md for syntax and precedence."""
    raise NotImplementedError


def to_dot(r: Regex, alphabet: Set[str]) -> str:
    """
    Return a Graphviz DOT string representing the finite state graph
    of r over the given alphabet. See SPEC.md for format requirements.
    """
    raise NotImplementedError


def compile_to_c(r: Regex, alphabet: Set[str]) -> str:
    """
    Generate C source code implementing the DFA for r over the given alphabet.
    The compiled binary reads lines from stdin and prints 'accept' or 'reject'
    for each line. See SPEC.md for full specification.
    """
    raise NotImplementedError


def generate_flex_spec(r: Regex, alphabet: Set[str]) -> str:
    """
    Generate a flex (.l) specification file encoding the DFA for r over
    the given alphabet. See SPEC.md for full specification.
    """
    raise NotImplementedError
