"""Type representations for Hindley-Milner type inference.

Defines monomorphic types (Type) and polymorphic type schemes (Scheme).
Types are frozen dataclasses for hashability and structural equality.
"""
from dataclasses import dataclass


class Type:
    """Base class for monomorphic types."""
    pass


@dataclass(frozen=True)
class TInt(Type):
    """Integer type."""
    def __repr__(self):
        return "int"


@dataclass(frozen=True)
class TBool(Type):
    """Boolean type."""
    def __repr__(self):
        return "bool"


@dataclass(frozen=True)
class TUnit(Type):
    """Unit type."""
    def __repr__(self):
        return "unit"


@dataclass(frozen=True)
class TVar(Type):
    """Type variable (may be free or bound by a Scheme)."""
    name: str

    def __repr__(self):
        return self.name


@dataclass(frozen=True)
class TArrow(Type):
    """Function type: arg -> ret."""
    arg: Type
    ret: Type

    def __repr__(self):
        return f"({self.arg} -> {self.ret})"


@dataclass(frozen=True)
class TPair(Type):
    """Pair type: fst * snd."""
    fst: Type
    snd: Type

    def __repr__(self):
        return f"({self.fst} * {self.snd})"


@dataclass(frozen=True)
class TList(Type):
    """List type: elem list."""
    elem: Type

    def __repr__(self):
        return f"{self.elem} list"


@dataclass
class Scheme:
    """Polymorphic type scheme: forall vars. body.

    vars is a frozenset of type variable names that are universally quantified.
    body is the underlying monomorphic type (may contain the quantified vars).
    """
    vars: frozenset  # frozenset of str
    body: Type

    def __repr__(self):
        if not self.vars:
            return repr(self.body)
        return f"forall {' '.join(sorted(self.vars))}. {self.body}"
