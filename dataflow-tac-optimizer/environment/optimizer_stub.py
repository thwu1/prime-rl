
"""Stub optimizer — replace this with your implementation."""

from tac_parser import Function
from typing import List


def optimize(functions: List[Function]) -> List[Function]:
    """Optimize the given list of TAC functions.

    Must implement:
    - Constant propagation & folding
    - Dead code elimination
    - Common subexpression elimination
    - Unreachable code elimination

    Iterate to a fixed point.
    """
    # TODO: implement optimization passes
    return functions
