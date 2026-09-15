#!/usr/bin/env python3

"""IR Optimizer — implement dataflow-based optimizations.

This file is the main entry point for the optimizer.  Implement the
``optimize()`` function so that it applies the following passes to
every function in the program:

  1. Constant propagation with constant folding and unreachable-code
     elimination.
  2. Common-subexpression elimination (CSE).
  3. Dead-code elimination via liveness / use-def analysis.

The optimized program MUST produce exactly the same printed output as
the original when run through the interpreter.

Usage:
    python3 optimize.py <input.ir> <output.ir>
"""

import sys
from ir_parser import parse_program
from ir_emitter import emit_program


def optimize(program):
    """Apply optimization passes to *program* and return the result.

    The returned program must be semantically equivalent to the input
    (identical interpreter output) but should contain fewer
    instructions wherever the analyses expose redundancy.
    """
    # TODO: implement optimization passes
    return program


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.ir output.ir", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        source = f.read()

    prog = parse_program(source)
    optimized = optimize(prog)

    with open(sys.argv[2], 'w') as f:
        f.write(emit_program(optimized))
