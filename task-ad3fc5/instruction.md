The file `/app/hsm.c` contains a skeleton for a Hierarchical State Machine (HSM) dispatch engine with two stub functions: `hsm_init()` and `hsm_dispatch()`. You must provide working implementations for both.

## Provided Files

- `/app/hsm.h` -- Engine API: data structures, function signatures, macros for state handlers
- `/app/hsm.c` -- Skeleton with `hsm_ctor()` and `hsm_top()` implemented; `hsm_init()` and `hsm_dispatch()` are stubs
- `/app/spec.md` -- Handler protocol reference (how state handlers communicate with the engine)
- `/app/test_sm.h` / `/app/test_sm.c` -- A 7-state test state machine with 4 nesting levels, 9 signal types, guard conditions, and various transition topologies
- `/app/main.c` -- Interactive driver that reads commands from stdin and prints action traces
- `/app/traces/input.txt` -- Reference input sequence covering all transition topologies
- `/app/traces/expected.txt` -- Expected output for the reference input sequence
- `/app/Makefile` -- Build system (`make` produces `/app/hsm_test`)

## Requirements

Your implementation must produce correct action traces for the test state machine across all transition topologies present in `test_sm.c`. Use the reference traces in `/app/traces/` to validate your implementation against the expected behavior:

```
cat /app/traces/input.txt | /app/hsm_test | diff - /app/traces/expected.txt
```

Build with `cd /app && make`. Run `/app/hsm_test` with commands piped to stdin (e.g., `INIT`, `P`, `Q`, ..., `X`, `STATE`, `FOO`).

Your implementation must also:
- Pass memory-safety validation under `valgrind --error-exitcode=42 --leak-check=full /app/hsm_test` with zero errors on the reference input sequence
- Compile and run cleanly when built with `-fsanitize=undefined -fno-sanitize-recover=all`