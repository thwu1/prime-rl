`/app/ir_interpreter.py` is an interpreter for a simple three-address code (TAC) intermediate representation. Six IR programs of varying complexity are in `/app/programs/` (`prog1.ir` through `prog6.ir`). The interpreter source defines the complete IR format and execution semantics.

`/app/optimize.py` is a stub that passes IR through unchanged. `/app/Makefile` has incomplete build targets.

## Requirements

**Optimizer** (`/app/optimize.py`):

- `python3 /app/optimize.py <file.ir>` — emit optimized IR to stdout. The optimized IR must produce identical output to the original when run through `/app/ir_interpreter.py`, and must contain meaningfully fewer instructions for every program.
- `python3 /app/optimize.py --dot <file.ir>` — emit a valid Graphviz DOT-format control flow graph to stdout, renderable by `dot` to SVG. The CFG must accurately represent the program's basic-block structure and all control-flow edges (including back-edges for loops and branch edges for conditionals). Nodes should use box shape and include instruction content in labels.

**Build pipeline** (`/app/Makefile`):

Complete the Makefile so that `make all` orchestrates the full pipeline: optimizing all six programs to `/app/output/`, verifying semantic equivalence via interpreter output comparison, generating DOT CFGs and SVG renders to `/app/cfg/`, and producing an optimization report at `/app/output/report.txt` with per-program statistics. Individual targets `optimize`, `verify`, `cfg`, `report`, and `clean` must work standalone.

The programs exercise inter-block control flow including loops, conditionals, and unconditional jumps. Several programs contain control-flow-sensitive semantics at join points and loop-carried dependencies.