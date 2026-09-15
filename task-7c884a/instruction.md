A working SSA-form IR optimizer is at `/app/tools/ir-opt`. It supports four optimization passes (`--cse`, `--constfold`, `--dce`, `--canonicalize`) and `--split-input-file` for multi-function inputs separated by `// -----` markers. Six IR input files in `/app/inputs/` exercise different optimizer behaviors.

Create a comprehensive `lit`/`FileCheck` test suite in `/app/tests/` and a pass-behavior analysis report at `/app/analysis.json`.

**Test suite requirements:**

- `/app/tests/lit.cfg.py` — working lit configuration that discovers `.test` files and defines a `%ir-opt` substitution pointing to the optimizer
- At least 6 `.test` files that test all four passes individually and in multi-pass combinations
- The tests must collectively use ALL of these FileCheck features: `CHECK-LABEL`, `CHECK-DAG`, `CHECK-NOT`, `CHECK-SAME`, variable capture (`[[VAR:pattern]]`), `--implicit-check-not`, and `--split-input-file`
- Every test file must have a `// RUN:` line and at least 3 CHECK directives
- `lit /app/tests/ -v` must exit 0 with all tests passing

**Analysis report:** Create `/app/analysis.json` conforming to the schema in `/app/analysis_schema.json`. Each question requires running `ir-opt` with specific passes on the corresponding input file in `/app/inputs/` and evaluating the output to determine the answer. The questions probe edge cases and subtle interactions between passes.

`lit` and `FileCheck` are pre-installed. The `ir-opt` tool reads IR from a file argument or stdin and writes transformed IR to stdout.