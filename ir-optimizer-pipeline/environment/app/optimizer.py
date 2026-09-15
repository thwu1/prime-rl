
"""
IR Optimizer — implement your optimization passes here.

Your task: implement the optimize() function so that it transforms IR programs
to use fewer instructions while preserving their observable behavior (same output
for the same input).

The function must handle all IR instruction types defined in ir.py.
"""

from ir import Instruction


def optimize(instructions: list[Instruction]) -> list[Instruction]:
    """
    Optimize the given list of IR instructions.

    Must preserve program semantics: the optimized program must produce
    the same output as the original for any given input.

    Returns the optimized list of IR instructions.
    """
    # TODO: Implement optimization passes including:
    # - Constant folding and propagation
    # - Dead code elimination (using liveness analysis)
    # - Copy propagation
    # - Dead branch elimination
    # - Unreachable code elimination
    return list(instructions)
