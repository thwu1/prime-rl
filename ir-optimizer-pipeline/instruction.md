A compiler IR toolchain at `/app/` includes IR data structures (`/app/ir.py`), an interpreter (`/app/ir_interpreter.py`), and 16 test programs (`/app/programs.py`). The `ircc` tool (`ircc --help`) provides utilities for inspecting programs, analyzing control flow, and testing optimizations.

The optimizer (`/app/optimizer.py`) reads `/app/pipeline.toml` to discover pass modules in `/app/passes/` and applies them iteratively until convergence. Each pass module must export `run(instructions) -> instructions` operating on IR `Instruction` objects (see `/app/ir.py`).

The 16 programs exhibit diverse optimization patterns including constant expressions, algebraic identities involving dynamic operands, repeated subexpressions across straight-line code, dead computations, unreachable branches, and copy chains. Some programs contain correctness traps — variables reassigned across loop back-edges or branch merge points where over-eager analysis breaks observable semantics. Several programs require multiple distinct analysis-driven transformations to interact across iterations before their optimization potential is fully realized; a single pass type applied in isolation will not meet their thresholds.

Create passes in `/app/passes/` and configure `/app/pipeline.toml` to achieve at least 35% total instruction reduction across all programs while preserving observable behavior (identical output for identical input). Each program has an individual minimum reduction threshold — use `ircc list` to see them.

Run tests with: `cd /app && python3 -m pytest /tests/test_state.py -v`