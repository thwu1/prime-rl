`/app/newton_schulz.py` implements Newton-Schulz iterative methods for approximating the orthogonal polar factor of a matrix. Two variants are defined:

- `newtonschulz5`: A fully working quintic (degree-5) variant that achieves adequate orthogonalization in 5 iterations.
- `newtonschulz7`: An incomplete septic (degree-7) variant with placeholder coefficients `(1, 0, 0, 0)` and an empty iteration body.

Complete `newtonschulz7` with optimal coefficients and a correct implementation that achieves equivalent orthogonalization quality in only 3 iterations. Convergence constraints for the coefficients are specified in `/app/config.json`. The coefficient `a` must be at least 4.0.

The implementation must correctly handle square, tall (m > n), and wide (m < n) matrices. After 3 septic iterations, `orthogonality_error(X)` must be below 0.5 for matrices up to 256×128, and within 0.15 of the quintic 5-step error on the same input.

Benchmark septic 3-step against quintic 5-step across all matrix sizes in the config, then write results to `/app/results.json`:

```json
{
  "septic_coefficients": {"a": <float>, "b": <float>, "c": <float>, "d": <float>},
  "constraint_satisfied": true,
  "max_deviation": <float>,
  "slope_at_zero": <float>,
  "benchmark": {
    "quintic_5step_errors": [<float>, ...],
    "septic_3step_errors": [<float>, ...],
    "matrix_sizes": [[<int>, <int>], ...]
  }
}
```

- `constraint_satisfied` must be `true`.
- `max_deviation` and `slope_at_zero` must be consistent with independent recomputation from the reported coefficients.
- Benchmark arrays must have one entry per configured matrix size. Each entry is the mean `orthogonality_error` over the configured trials. All errors must be finite and in `[0, 2)`.