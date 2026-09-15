"""
optimize.py - Optimization pass for the toy SSA IR.


Implement the three functions below.  The IR data model is in ir.py.
Use irtool.py and the benchmarks in /app/benchmarks/ to explore.
"""
from typing import Dict, List, Optional
from ir import Function


def compute_rpo(func: Function) -> List[str]:
    """Return block names in reverse post-order."""
    raise NotImplementedError


def compute_dominators(func: Function, rpo: List[str]) -> Dict[str, Optional[str]]:
    """Return immediate dominator for each block (entry maps to None)."""
    raise NotImplementedError


def optimize(func: Function) -> Function:
    """Eliminate redundant operations. Modify func in-place and return it."""
    raise NotImplementedError
