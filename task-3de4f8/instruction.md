Complete the program synthesizer in `/app/synthesize.py` so that it can automatically discover programs in a provided DSL that are functionally equivalent to black-box oracle functions.

## Environment

`/app/dsl.py` defines a straight-line DSL with 10 operations (`add`, `sub`, `mul`, `and`, `or`, `xor`, `shl`, `shr`, `neg`, `not`) over 16-bit unsigned integers. A program is a sequence of instructions; each instruction selects an operation and two operand registers. Registers `z0`-`z3` hold the four input values; each instruction appends a new register. The output is the last register's value.

`/app/oracle.py` provides 5 oracle functions, each mapping `(a, b, c, d) -> int` with all values in `[0, 0xFFFF]`. The oracle implementations must be treated as opaque—you may only call them, not inspect their source to extract the answer.

`/app/synthesize.py` contains a stub `synthesize(oracle_fn, max_lines=5)` function. It must accept **any** callable oracle `(a, b, c, d) -> int`—not just the 5 provided—and return a valid DSL program (list of instruction dicts) that computes the same function as the oracle on all possible 16-bit inputs, or `None` on failure. Programs must use at most `max_lines` instructions.

## Goal

Implement `synthesize()` such that it reliably produces correct programs for the 5 provided oracles and generalizes to previously unseen oracle functions of comparable complexity (up to 3-4 composed operations). The synthesizer must handle the full 10-operation DSL and work within reasonable time limits.

After implementation, run `python3 /app/synthesize.py all` to produce `/app/results/oracle_{1..5}.json`.