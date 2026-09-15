The file `/app/benchmarks.fpcore` contains four floating-point expressions in FPCore S-expression format. Each expression suffers from catastrophic cancellation or severe precision loss in certain regions of its input domain when evaluated naively in `float64` arithmetic. A reference guide to FPCore syntax is at `/app/docs/fpcore_syntax.txt`. A baseline accuracy measurement tool demonstrating the bits-of-accuracy methodology is at `/app/tools/profiler.py` (requires `mpmath`).

Examine the benchmark file, parse the FPCore expressions to extract mathematical formulas and input domains, diagnose each expression's numerical pathology, and produce implementations that recover high floating-point accuracy using only standard `float64` operations.

## Deliverables

### `/app/improved.py`

Python module containing four functions corresponding to the benchmark expressions in file order:

- `improved_1(x)` — `(exp(x) - 1 - x) / x²`
- `improved_2(x)` — `coth(x) - 1/x`
- `improved_3(x)` — `(sin(x) - x·cos(x)) / (x - sin(x))`
- `improved_4(x, y)` — `(exp(x) - exp(y)) / (x - y)`

Each function must:

- Accept the same parameters as the original FPCore definition
- Use only Python's `math` standard library — importing `mpmath`, `decimal`, or `gmpy` is forbidden (source code is inspected)
- Achieve at least **38 average bits of accuracy** (out of 53 possible for float64) when evaluated at 2000 sample points drawn from the expression's specified domain and compared against arbitrary-precision reference values computed at 60-digit precision
- Achieve at least **5 more average bits** of accuracy than the naive direct-translation implementation across the sampled domain (at least **3 more** for the second expression, where the naive retains partial accuracy over much of its range)
- Produce correct results at representative domain points with relative error below `1e-14` (below `1e-10` for the fourth expression, whose intermediate values can span large magnitudes)

### `/app/report.json`

Accuracy measurements for all four expressions in the following exact schema:

```json
{"expressions": [{"id": 1, "original_avg_bits": <float>, "improved_avg_bits": <float>}, ...]}
```

The `expressions` array must contain exactly 4 entries (one per benchmark expression, in order). Each entry requires fields `id` (integer 1–4), `original_avg_bits` (float), and `improved_avg_bits` (float). Every entry must satisfy `improved_avg_bits > original_avg_bits`.

Measure accuracy by sampling inputs across each expression's domain and comparing `float64` results against arbitrary-precision reference values computed at 60+ decimal digits of precision.