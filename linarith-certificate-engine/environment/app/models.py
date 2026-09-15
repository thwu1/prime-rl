
"""Data structures for the linear arithmetic unsatisfiability engine.

DO NOT MODIFY THIS FILE. Implement the required functions in engine.py.
"""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict


class CompType(Enum):
    """Comparison type for constraints in standard form (expr R 0)."""
    LT = "<"
    LE = "<="
    EQ = "="


@dataclass
class LinearExpr:
    """A linear expression: sum of coefficient * variable.

    Variables are identified by non-negative integer indices (x0, x1, ...).
    Index -1 represents the constant term.
    Coefficients are exact rationals (Fraction).
    """
    coeffs: Dict[int, Fraction] = field(default_factory=dict)

    def get(self, var: int) -> Fraction:
        return self.coeffs.get(var, Fraction(0))

    def set(self, var: int, val: Fraction) -> None:
        if val == Fraction(0):
            self.coeffs.pop(var, None)
        else:
            self.coeffs[var] = val

    def variables(self) -> set:
        return set(self.coeffs.keys())

    def is_zero(self) -> bool:
        return all(v == 0 for v in self.coeffs.values())

    def __add__(self, other: LinearExpr) -> LinearExpr:
        result = LinearExpr(dict(self.coeffs))
        for var, coeff in other.coeffs.items():
            new_val = result.get(var) + coeff
            result.set(var, new_val)
        return result

    def scale(self, factor: Fraction) -> LinearExpr:
        if factor == 0:
            return LinearExpr()
        return LinearExpr({v: c * factor for v, c in self.coeffs.items()})

    def __repr__(self):
        if not self.coeffs:
            return "0"
        terms = []
        for var in sorted(self.coeffs.keys()):
            c = self.coeffs[var]
            if var == -1:
                terms.append(str(c))
            else:
                terms.append(f"{c}*x{var}")
        return " + ".join(terms)


@dataclass
class Constraint:
    """A constraint in standard form: expr R 0."""
    expr: LinearExpr
    comp: CompType

    def __repr__(self):
        return f"{self.expr} {self.comp.value} 0"


@dataclass
class Certificate:
    """A certificate of unsatisfiability.

    Maps constraint indices to rational coefficients.
    """
    coefficients: Dict[int, Fraction] = field(default_factory=dict)

    def __repr__(self):
        return f"Certificate({dict(self.coefficients)})"
