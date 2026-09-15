A custom three-address code intermediate representation (IR) is defined in `/app/ir_spec.md`. A reference interpreter is provided at `/app/interpreter.py`. Five IR programs of increasing complexity reside in `/app/programs/prog1.ir` through `/app/programs/prog5.ir`, with their expected runtime outputs in `/app/expected_outputs/`.

Create `/app/optimizer.py` — a Python program that reads an IR file (path given as the first command-line argument), applies data-flow-driven compiler optimizations, and writes the optimized IR to stdout.

The optimizer must implement at minimum:

- **Constant propagation** (forward data-flow analysis with iterative fixed-point computation across basic blocks; must correctly handle merge points where different predecessors supply different constant values)
- **Common subexpression elimination** (using available-expression analysis; must handle expressions available across basic-block boundaries, not only within a single block)
- **Dead code elimination** (via liveness analysis — backward data-flow analysis; must iteratively remove instructions whose results become unused after other optimizations)

Requirements:

1. For every program `prog{1..5}.ir`, the optimized IR must be semantically equivalent to the original: `python3 /app/interpreter.py <optimized.ir>` must produce output identical to the corresponding file in `/app/expected_outputs/`.
2. The optimized IR must contain strictly fewer instructions than the original for every program.
3. Specific maximum instruction counts per program must be met (the tests enforce these thresholds).
4. The optimizer must converge: iterate the analysis/transformation passes until no further changes occur.