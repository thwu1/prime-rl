Build a program synthesis engine at `/app/synthesizer.py` that uses Z3 to synthesize straight-line bitvector programs from input-output examples.

## Environment

- `/app/dsl.py` — DSL specification: 16-bit unsigned bitvector arithmetic with 8 binary operators (`add`, `sub`, `mul`, `band`, `bor`, `bxor`, `shl`, `lshr`) and 3 named constants (`c0`=0, `c1`=1, `c65535`=65535). Programs are sequences of binary operations over input variables, constants, and previously computed temporaries.
- `/app/examples/` — Two example benchmarks with known solutions demonstrating the spec and solution JSON formats.
- Z3 (`z3-solver`) is pre-installed.

## Synthesizer Interface

`/app/synthesizer.py` must accept two command-line arguments:

```
python3 /app/synthesizer.py <spec.json> <output.json>
```

**Input spec format** (`spec.json`):
```json
{
  "num_inputs": 3,
  "max_ops": 5,
  "bit_width": 16,
  "io_pairs": [[[1, 2, 3], 42], ...]
}
```

**Output solution format** (`output.json`):
```json
{
  "program": [
    {"op": "add", "arg1": "x0", "arg2": "x1", "dest": "t0"},
    {"op": "mul", "arg1": "t0", "arg2": "x2", "dest": "t1"}
  ],
  "result": "t1"
}
```

The synthesizer must search for programs of increasing length (1 to `max_ops` operations) and return the first correct program found. Each operation applies one of the 8 DSL operators to two arguments drawn from input variables (`x0`–`xN`), constants (`c0`, `c1`, `c65535`), or earlier temporaries (`t0`, `t1`, ...). The result variable must be the last temporary assigned.

## Requirements

- The synthesizer must encode the synthesis problem as Z3 bitvector constraints and solve it — brute-force enumeration will not scale.
- Must correctly handle 16-bit wrapping arithmetic and shift semantics (shift amounts masked to 4 bits).
- Must produce valid solutions for benchmarks with 2–3 input variables and up to 4 operations within 4 minutes per benchmark.
- Exit code 0 on success with a valid solution JSON written to the output path.