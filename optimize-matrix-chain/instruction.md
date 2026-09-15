Implement `/app/optimizer.py` that reads generalized matrix chain (GMC) problems from `/app/problems/` and writes minimum-FLOP evaluation plans to `/app/output/<problem_id>.json`.

Each problem defines a chain of matrix terms (some transposed or inverted) with known dimensions and algebraic properties (diagonal, triangular, SPD). The optimizer must find the evaluation plan — parenthesization plus BLAS/LAPACK kernel selection — that minimizes total floating-point operations.

Key optimization opportunities include: using DIAGMM instead of GEMM when one operand is diagonal, TRSM instead of explicit inverse for triangular solves, POSV for SPD solves, choosing parenthesization to minimize intermediate sizes passed to solve kernels, exploiting property propagation through intermediates (e.g., product of two lower-triangular matrices is lower-triangular), and using right-solve kernels when an inverted term appears on the right side of a sub-expression.

The full kernel catalog with cost formulas, property propagation rules, and output format are specified in `/app/spec.md`.

Run the optimizer: `python3 /app/optimizer.py`