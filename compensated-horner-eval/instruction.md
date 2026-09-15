The SQLite database `/app/polyeval.db` contains polynomials with coefficients stored as JSON arrays (index `i` = coefficient of x^i). Several polynomials are severely ill-conditioned: evaluated at points near their roots, the true result is astronomically smaller than intermediate sums, so standard double-precision Horner evaluation loses virtually all significant digits to catastrophic cancellation.

Build a pipeline that evaluates these polynomials with accuracy far exceeding standard double-precision, using **only IEEE 754 binary64 `float` operations**. Arbitrary-precision or extended-precision libraries (`mpmath`, `decimal`, `fractions`, `sympy`, `gmpy2`) are prohibited in the evaluator.

For each polynomial, produce:
- A high-accuracy evaluated value
- A certified error bound: a non-negative number guaranteeing |true_value - computed_value| <= error_bound
- The standard Horner evaluation result

The high-accuracy evaluator must achieve at least **1000x lower error** than Horner for the ill-conditioned cases. All certified error bounds must be provably valid (the true value, via exact rational arithmetic, must lie within the certified interval).

## Required artifacts

**`/app/evaluator.py`** — Reads from the `polynomials` table in `/app/polyeval.db`, computes results, and writes them to a `results` table (columns: `poly_id`, `compensated_value`, `error_bound`, `naive_value`).

**`/app/Makefile`** — Targets:
- `all` (default): runs `evaluate` then `export`
- `evaluate`: executes the evaluator
- `export`: queries `results` joined with `polynomials` via `sqlite3` CLI, pipes through `jq`, producing `/app/results.json`

**`/app/results.json`** — Produced by `make export`. Must conform to `/app/schema.json`:

| Field               | Type   | Description                                    |
|---------------------|--------|------------------------------------------------|
| `name`              | string | Polynomial name from `polynomials` table       |
| `eval_point`        | number | The evaluation point                           |
| `compensated_value` | number | High-accuracy result                           |
| `error_bound`       | number | Certified bound on |true - computed|, >= 0     |
| `naive_value`       | number | Standard Horner result                         |

Running `make all` in `/app/` must execute the complete pipeline.