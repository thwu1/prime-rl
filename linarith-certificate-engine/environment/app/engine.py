
"""Linear arithmetic unsatisfiability engine.

Implement all functions below. See /app/models.py for data structure definitions.
"""

from fractions import Fraction
from typing import Dict, List, Optional, Tuple, Set
from models import CompType, LinearExpr, Constraint, Certificate


def parse_constraint(s: str) -> Constraint:
    """Parse a string like '2*x0 + -3*x1 + 1 < 0' into a Constraint."""
    raise NotImplementedError


def verify_certificate(constraints: List[Constraint], cert: Certificate) -> bool:
    """Return True iff cert is a valid unsatisfiability certificate for constraints."""
    raise NotImplementedError


def fourier_motzkin_oracle(constraints: List[Constraint]) -> Optional[Certificate]:
    """Find a certificate if the system is unsatisfiable; return None if satisfiable."""
    raise NotImplementedError


def simplex_oracle(constraints: List[Constraint]) -> Optional[Certificate]:
    """Independent oracle: find a certificate or return None."""
    raise NotImplementedError


def is_unsatisfiable(constraints: List[Constraint],
                     oracle: str = "fm") -> Tuple[bool, Optional[Certificate]]:
    """Dispatch to the named oracle. Returns (is_unsat, certificate_or_None)."""
    raise NotImplementedError


def export_lp(constraints: List[Constraint], filepath: str) -> None:
    """Export the constraint system to a CPLEX LP format file for glpsol."""
    raise NotImplementedError


def validate_with_glpsol(filepath: str) -> str:
    """Run glpsol on an LP file, return 'FEASIBLE' or 'INFEASIBLE'."""
    raise NotImplementedError
