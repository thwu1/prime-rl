"""Unification algorithm for Hindley-Milner type inference.

Implements Robinson's unification with occurs check.
"""

from ml_types import Type, TInt, TBool, TUnit, TVar, TArrow, TPair, TList


class UnificationError(Exception):
    """Raised when two types cannot be unified."""
    pass


class Substitution:
    """A type substitution: mapping from type variable names to types."""

    def __init__(self, mapping=None):
        self.mapping = mapping if mapping is not None else {}

    def apply(self, t):
        """Apply this substitution to a type, resolving all type variables."""
        if isinstance(t, (TInt, TBool, TUnit)):
            return t
        elif isinstance(t, TVar):
            if t.name in self.mapping:
                return self.apply(self.mapping[t.name])
            return t
        elif isinstance(t, TArrow):
            return TArrow(self.apply(t.arg), self.apply(t.ret))
        elif isinstance(t, TPair):
            return TPair(self.apply(t.fst), self.apply(t.snd))
        elif isinstance(t, TList):
            return TList(self.apply(t.elem))
        else:
            raise ValueError(f"Unknown type: {type(t)}")

    def compose(self, other):
        """Compose: (self . other)(t) = self(other(t)).

        Apply other first, then self.
        """
        new_mapping = {}
        for k, v in other.mapping.items():
            new_mapping[k] = self.apply(v)
        for k, v in self.mapping.items():
            if k not in new_mapping:
                new_mapping[k] = v
        return Substitution(new_mapping)

    def __repr__(self):
        return f"Subst({self.mapping})"


def _occurs_in(name, t):
    """Check whether type variable 'name' occurs anywhere in type t."""
    if isinstance(t, TVar):
        return t.name == name
    elif isinstance(t, TArrow):
        return _occurs_in(name, t.arg) or _occurs_in(name, t.ret)
    elif isinstance(t, TPair):
        return _occurs_in(name, t.fst) or _occurs_in(name, t.snd)
    elif isinstance(t, TList):
        return _occurs_in(name, t.elem)
    else:
        return False


def _bind(name, t):
    """Create a substitution binding 'name' to t, with occurs check."""
    if isinstance(t, TVar) and t.name == name:
        return Substitution()
    if _occurs_in(name, t):
        raise UnificationError(f"Infinite type: {name} occurs in {t}")
    return Substitution({name: t})


def unify(t1, t2):
    """Compute the most general unifier of t1 and t2.

    Returns a Substitution s such that s(t1) = s(t2).
    Raises UnificationError if no unifier exists.
    """
    if isinstance(t1, TVar):
        return _bind(t1.name, t2)
    elif isinstance(t2, TVar):
        return _bind(t2.name, t1)
    elif isinstance(t1, TInt) and isinstance(t2, TInt):
        return Substitution()
    elif isinstance(t1, TBool) and isinstance(t2, TBool):
        return Substitution()
    elif isinstance(t1, TUnit) and isinstance(t2, TUnit):
        return Substitution()
    elif isinstance(t1, TArrow) and isinstance(t2, TArrow):
        s1 = unify(t1.arg, t2.arg)
        s2 = unify(s1.apply(t1.ret), s1.apply(t2.ret))
        return s2.compose(s1)
    elif isinstance(t1, TPair) and isinstance(t2, TPair):
        s1 = unify(t1.fst, t2.fst)
        s2 = unify(s1.apply(t1.snd), s1.apply(t2.snd))
        return s2.compose(s1)
    elif isinstance(t1, TList) and isinstance(t2, TList):
        return unify(t1.elem, t2.elem)
    else:
        raise UnificationError(f"Cannot unify {t1} with {t2}")
