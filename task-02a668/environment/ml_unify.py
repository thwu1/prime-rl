"""Type unification for Mini-ML type inference."""
from ml_types import Type, TInt, TBool, TUnit, TVar, TArrow, TPair, TList


class UnificationError(Exception):
    """Raised when two types cannot be unified."""
    pass


class Substitution:
    """Maps type variable names to types."""

    def __init__(self, mapping=None):
        self.mapping = mapping if mapping is not None else {}

    def apply(self, t):
        """Apply this substitution to a type, returning the result."""
        raise NotImplementedError

    def compose(self, other):
        """Return a new substitution that is the composition of self and other."""
        raise NotImplementedError


def unify(t1, t2):
    """Find a substitution s such that s(t1) = s(t2).

    Raises UnificationError if no such substitution exists.
    """
    raise NotImplementedError
