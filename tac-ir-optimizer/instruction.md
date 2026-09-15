`/app/interpreter.py` is an interpreter for a custom three-address code (TAC) intermediate representation. `/app/tac_check.py` is a structural validator for TAC programs. `/app/programs/` contains 10 TAC programs, each defining a `target` function.

Build two artifacts:

## `/app/optimizer.py`

A Python script that takes a `.tac` file path as its sole command-line argument and writes a semantically equivalent, optimized TAC program to stdout:

    python3 /app/optimizer.py /app/programs/example.tac

Exit code must be 0 on success. The optimized output must satisfy three properties:

1. **Structural validity**: `python3 /app/tac_check.py <optimized_file>` must exit 0.
2. **Semantic preservation**: `python3 /app/interpreter.py <optimized_file> target` must print the same integer as interpreting the original.
3. **Instruction count thresholds**: the `target` function in the optimized output must contain at most the allowed number of instructions per the table below, and at least 1 (every function must retain its `return`).

An "instruction" is any non-blank, non-comment line inside `function target(...)` that is not a function header (`function name(...):`) and not a label (`name:`). Assignments, returns, jumps, conditional jumps, and calls all count.

| Program | Expected return value | Max instructions in `target` |
|---|---|---|
| `pure_fold.tac` | 361 | 2 |
| `propagate_fold.tac` | 20 | 2 |
| `dead_stores.tac` | 57 | 2 |
| `unreachable.tac` | 15 | 5 |
| `loop_optimization.tac` | 45 | 9 |
| `cascading.tac` | 10 | 2 |
| `diamond_cfg.tac` | 9 | 5 |
| `copy_chain.tac` | 42 | 2 |
| `recursive_call.tac` | 720 | 4 |
| `overflow.tac` | 1 | 2 |

## `/app/Makefile`

A GNU Makefile that orchestrates the full optimization pipeline. Required targets:

- **`make all`** (default): optimizes every program in `/app/programs/`, validates each output, and generates a JSON report.
- **`output/<name>.tac`**: optimizes `programs/<name>.tac` into `output/<name>.tac` using the optimizer. Must use file-level dependencies so that `make` only re-optimizes programs whose source `.tac` file (or `optimizer.py`) has changed since the last run.
- **`make report`**: generates `/app/output/report.json` — a JSON array where each element is an object with exactly these fields and types:
  - `"program"` (string): base filename without `.tac` extension
  - `"original_ret"` (integer): return value from `python3 interpreter.py <original> target`
  - `"optimized_ret"` (integer): return value from `python3 interpreter.py <optimized> target`
  - `"match"` (boolean): whether `original_ret == optimized_ret`
  - `"instruction_count"` (integer): instruction count in the optimized `target` function (using the counting method above)
  - `"valid"` (boolean): whether the optimized program passes `tac_check.py`

You may create additional helper scripts in `/app/` as needed. The interpreter source is the authoritative TAC language specification. Examine the provided programs to determine which transformations are effective.