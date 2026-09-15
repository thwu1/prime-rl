Three C shared libraries at `/app/parsers/` each implement `fast_parse_double(const char *str, int len, double *result)` for converting decimal strings to IEEE 754 binary64 doubles. Each uses a different fast-path/slow-path strategy and each has distinct correctness defects. Source code is alongside the `.so` files. A dataset of number strings is at `/app/data/input.txt`. The pipeline at `/app/pipeline.py` computes aggregate statistics (XOR hash, Kahan sum, subnormal count, negative-zero count) from parsed values.

Produce the following at `/app/`:

1. **`conformance_tests.csv`** — A conformance test corpus (CSV with columns `input_string,category`) covering at least these IEEE 754 edge-case categories with ≥3 entries each: `negative_zero`, `subnormal`, `boundary`, `precision`, `overflow`.

2. **`evaluation.json`** — An evaluation report comparing all three parsers against Python's `float()` as the IEEE 754 reference. Must contain:
   - `ranking`: list of parser names ordered best (fewest failures) to worst
   - Per-parser entry (keyed `alpha`, `beta`, `gamma`) with `failure_count` (int) and `categories` (dict mapping category name to failure count)

3. **`libconformant.so`** — A conformant parser (source at `/app/src/conformant.c`, buildable via `make libconformant.so`) that produces bit-exact IEEE 754 results for all inputs including negative zeros, subnormals, boundary values, and overflow.

4. **`results.json`** — Correct pipeline output: `python3 /app/pipeline.py --lib /app/libconformant.so`