"""
First-order term representation for term rewriting systems.

"""

from __future__ import annotations
from typing import Dict, List, Set, Tuple


class Var:
    """A variable in a first-order term."""
    __slots__ = ('name',)

    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Var) and self.name == other.name

    def __hash__(self):
        return hash(('Var', self.name))

    def __repr__(self):
        return self.name


class Fun:
    """A function application f(t1, ..., tn) in a first-order term."""
    __slots__ = ('symbol', 'args')

    def __init__(self, symbol: str, args: Tuple = ()):
        self.symbol = symbol
        self.args = tuple(args)

    def __eq__(self, other):
        return (isinstance(other, Fun)
                and self.symbol == other.symbol
                and self.args == other.args)

    def __hash__(self):
        return hash(('Fun', self.symbol, self.args))

    def __repr__(self):
        if not self.args:
            return self.symbol
        return f"{self.symbol}({', '.join(repr(a) for a in self.args)})"


def variables(t) -> Set[str]:
    """Collect all variable names occurring in a term."""
    if isinstance(t, Var):
        return {t.name}
    result: Set[str] = set()
    for a in t.args:
        result |= variables(a)
    return result


def apply_subst(t, subst: Dict[str, object]) -> object:
    """Apply a substitution mapping variable names to terms."""
    if isinstance(t, Var):
        return subst.get(t.name, t)
    return Fun(t.symbol, tuple(apply_subst(a, subst) for a in t.args))


def term_size(t) -> int:
    """Count the total number of nodes (variables + function symbols)."""
    if isinstance(t, Var):
        return 1
    return 1 + sum(term_size(a) for a in t.args)


def subterms_with_positions(t) -> List[Tuple[Tuple[int, ...], object]]:
    """Return all (position, subterm) pairs. Position () denotes the root."""
    result = [((), t)]
    if isinstance(t, Fun):
        for i, arg in enumerate(t.args):
            for pos, sub in subterms_with_positions(arg):
                result.append(((i,) + pos, sub))
    return result


def replace_at_position(t, pos: Tuple[int, ...], replacement) -> object:
    """Replace the subterm at a given position with a new term."""
    if not pos:
        return replacement
    if not isinstance(t, Fun):
        raise ValueError(f"Cannot descend into variable at position {pos}")
    idx = pos[0]
    new_args = list(t.args)
    new_args[idx] = replace_at_position(t.args[idx], pos[1:], replacement)
    return Fun(t.symbol, tuple(new_args))


def rename_variables(t, suffix: str) -> object:
    """Create a copy of a term with all variables renamed by appending suffix."""
    if isinstance(t, Var):
        return Var(t.name + suffix)
    return Fun(t.symbol, tuple(rename_variables(a, suffix) for a in t.args))
