"""Type inference for Mini-ML."""
from ml_ast import *
from ml_types import Type, TInt, TBool, TUnit, TVar, TArrow, TPair, TList, Scheme
from ml_unify import Substitution, UnificationError, unify


class InferenceError(Exception):
    """Raised when type inference fails."""
    pass


class TypeEnv:
    """Type environment: maps variable names to type schemes."""

    def __init__(self, bindings=None):
        self.bindings = bindings if bindings is not None else {}

    def extend(self, name, scheme):
        """Return a new environment with an additional binding."""
        new = dict(self.bindings)
        new[name] = scheme
        return TypeEnv(new)

    def lookup(self, name):
        """Look up a variable's type scheme. Raises InferenceError if unbound."""
        if name not in self.bindings:
            raise InferenceError(f"Unbound variable: {name}")
        return self.bindings[name]


def infer_program(expr):
    """Infer the type of a top-level expression.

    Returns the principal type or raises InferenceError.
    """
    raise NotImplementedError
