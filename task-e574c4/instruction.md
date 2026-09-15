A TAC intermediate representation environment is provided at `/app/`:

- `/app/interpreter.py` — executes TAC programs (`python3 /app/interpreter.py <file.tac>`)
- `/app/tac_validate.py` — validates TAC structural well-formedness; exits 0 on valid input
- `/app/ir_spec.md` — TAC format specification
- `/app/programs/` — five TAC programs: `const_fold.tac`, `dead_stores.tac`, `cse.tac`, `loop_combined.tac`, `nested_flow.tac`

Graphviz (`dot`) and LLVM tools (`llvm-as`, `lli`) are installed.

Create `/app/optimize.sh` (executable, takes one TAC file path argument) that produces three outputs:

- **Optimized TAC to stdout** — semantically equivalent to the original, valid per `tac_validate.py`
- **Graphviz DOT CFG** at `/app/cfg_output/<basename>.dot` — renderable by `dot -Tsvg`, with nodes for every basic block label and directed edges for all control-flow transitions
- **LLVM IR translation** at `/app/llvm_output/<basename>.ll` — a valid LLVM IR module that assembles cleanly via `llvm-as` and executes via `lli` producing byte-identical printed output to the original TAC program

## Optimization Requirements

- **Constant propagation/folding**: no `var = <int> <op> <int>` may remain; resolve constant branches to unconditional jumps
- **Dead code elimination** (liveness-based): all `dead*`-named variables eliminated; unreachable blocks removed
- **Common sub-expression elimination**: in `cse.tac`, `a + b` and `a * b` each computed at most once in function `compute`

The optimizer must handle loops via iterative dataflow, multiple functions, function calls, and inter-pass interactions.

## Instruction Count Limits (executable lines only)

| Program | Max |
|---|---|
| `const_fold.tac` | 10 |
| `dead_stores.tac` | 12 |
| `cse.tac` | 16 |
| `loop_combined.tac` | 18 |
| `nested_flow.tac` | 25 |

## LLVM IR Requirements

Each generated module at `/app/llvm_output/<basename>.ll` must assemble to bitcode via `llvm-as` (exit code 0) and execute via `lli` to produce output identical to the original TAC program run through `/app/interpreter.py`. The IR must correctly translate all TAC operations including arithmetic, comparisons, logical operators, branches, function calls with arguments, and PRINT statements (using C `printf`).