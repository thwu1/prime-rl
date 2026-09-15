The `/app/` directory contains a broken fixed-point signal processing pipeline. Building with `make -C /app` produces two binaries:

- `/app/pipeline` — Reads autocorrelation data in Double Precision Format (DPF) from stdin and outputs filter coefficients and reflection coefficients.
- `/app/selftest` — Runs self-consistency checks on the arithmetic library.

**`pipeline` input** (stdin, 11 lines):
```
Rh[0] Rl[0]
Rh[1] Rl[1]
...
Rh[10] Rl[10]
```
Each line: two space-separated 16-bit signed integers representing the high and low parts of a DPF pair.

**`pipeline` output** (stdout, 15 lines):
```
A[0]
A[1]
...
A[10]
rc[0]
rc[1]
rc[2]
rc[3]
```
Each line: one 16-bit signed integer. `A[0]` is always 4096.

**Requirements:**

1. `make -C /app` compiles without errors, producing both `pipeline` and `selftest`.
2. `/app/selftest` reports all checks passing (exit code 0).
3. `/app/pipeline` produces bit-exact correct output for all valid DPF autocorrelation inputs.

The Makefile supports `all` (default), `debug` (with debug symbols for `gdb`), and `clean` targets.

**Modifiable files:** `/app/basicop.c`, `/app/oper_32b.c`, `/app/levinson.c`.

**Do not modify:** `/app/pipeline.c`, `/app/selftest.c`, `/app/Makefile`, `/app/basicop.h`, `/app/oper_32b.h`, `/app/levinson.h`.
