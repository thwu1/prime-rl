A toy SSA IR framework (`/app/ir.py`), CLI toolkit (`/app/irtool.py`), and unoptimized benchmark programs (`/app/benchmarks/*.ir`) are provided.

Implement `/app/optimize.py` exporting three functions matching the signatures in the existing stub:

- `compute_rpo(func)` returning block names in reverse post-order
- `compute_dominators(func, rpo)` returning a dict mapping each block to its immediate dominator (`None` for entry block)
- `optimize(func)` returning the function modified in-place with redundant operations eliminated

The optimizer must preserve exact interpreter output while eliminating as many redundant instructions and phi nodes as possible across all blocks in the control-flow graph. Examine the benchmarks using the CLI tool (`python3 /app/irtool.py --help`) to discover what classes of redundancy your optimizer needs to handle.

Caution: the IR's memory and side-effecting operations require sound reasoning about when cached heap state remains valid across instructions and across basic block boundaries.