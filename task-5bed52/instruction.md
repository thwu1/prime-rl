Three programs in three-address code (TAC) intermediate representation are at `/app/programs/*.tac`. Each contains a function with labeled basic blocks, conditional/unconditional jumps, and arithmetic operations. Examine the files to understand the instruction format.

Build `/app/optimizer.py` that parses all `.tac` files and writes per-program results to `/app/results/`:

- `<name>.cfg.json` — CFG adjacency list: `{"block": ["successors", ...]}`
- `<name>.live.json` — per-block sorted variable lists of live-in variables (may be read before redefinition on some path leaving the block)
- `<name>.reaching.json` — per-block sorted lists of `[var, defining_block, def_index]` triples representing definitions reaching block entry
- `<name>.avail.json` — per-block sorted lists of `[operand1, op, operand2]` triples for binary expressions guaranteed available at block entry (computed and not killed on every path)
- `<name>.constprop.json` — per-block maps `{var: value}` using lattice values `"TOP"` (undetermined), `"BOT"` (conflicting), or an integer constant, representing provable variable state at block entry
- `<name>.opt.tac` — semantically equivalent TAC with strictly fewer instructions, produced by applying constant folding, common subexpression elimination, and dead code elimination to a global fixpoint

All four dataflow analyses must use iterative worklist-based solvers with correct lattice semantics, direction (forward/backward), initialization, and meet/transfer functions.

Build `/app/Makefile` with these targets:

- `analyze` — runs the optimizer
- `visualize` — renders each CFG as `/app/results/<name>.cfg.svg` using graphviz `dot`
- `report` — uses `jq` to merge all per-program constprop results into `/app/results/summary.json` as `{"<name>": <constprop_data>, ...}`
- `all` — runs analyze, visualize, and report in sequence

Validate by running `cd /app && make all`.