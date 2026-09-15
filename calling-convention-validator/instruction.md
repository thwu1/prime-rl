Build a cross-compiler calling convention validator for the x86-64 System V ABI at `/app/`.

The tool must generate at least 50 self-checking C test program pairs (separate `caller_NNN.c` and `callee_NNN.c` files), compile each pair as separate translation units with four compiler combinations (gcc caller + gcc callee, clang caller + clang callee, gcc caller + clang callee, clang caller + gcc callee), run all binaries, and produce a conformance report.

Each callee function receives parameters, validates they match expected values, and returns an error count. Each caller passes known values and checks the callee's return. Separate compilation (no cross-translation-unit inlining) is mandatory to ensure parameters actually traverse the ABI boundary.

## ABI Coverage

Tests must exercise these scenarios (at least 2 tests per scenario):

- **integer_regs**: Integer parameters allocated to rdi/rsi/rdx/rcx/r8/r9 and stack overflow beyond 6 registers
- **sse_regs**: float/double parameters allocated to xmm0-xmm7 and stack overflow beyond 8 registers
- **mixed_params**: Interleaved integer and floating-point parameters consuming both register files
- **struct_small**: Structs <= 8 bytes (single eightbyte, INTEGER or SSE classification)
- **struct_medium**: Structs 9-16 bytes (two-eightbyte classification across register pairs)
- **struct_large**: Structs > 16 bytes (MEMORY class, passed via caller-allocated hidden pointer)
- **return_values**: Struct return value classification (register pair return vs. hidden pointer for large structs)
- **variadic**: Variadic function parameter passing via va_list with mixed types

## Output

- `/app/generated/caller_NNN.c` and `/app/generated/callee_NNN.c` — generated test source files
- `/app/generated/headers/` — shared type definitions for struct tests
- `/app/results/summary.json` — structured conformance results
- `/app/results/report.tap` — TAP-format test report

### summary.json schema

`total_tests` (int), `scenarios` (list of scenario name strings), `results` (dict mapping each compiler combo key like `"gcc_gcc"` to `{"pass": N, "fail": N, "error": N}`), and `test_details` (list of per-test objects each containing `test_id`, `scenario`, `description`, and a pass/fail/error string for each of the four compiler combo keys).