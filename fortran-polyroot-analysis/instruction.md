Six polynomials of varying degree and numerical conditioning are defined in `/app/polynomials.json` (coefficients in descending order: highest degree first). Pre-computed root-finding results are in `/app/claimed_results.json`. An automated CI pipeline flagged anomalies in the submission but reported neither which entries are affected nor what is wrong.

Audit the claimed results. Determine which polynomial entries contain defects and which are correct. For each defective entry, classify and explain the nature of the defect. Produce corrected roots for all six polynomials, and compare at least three distinct root-finding algorithms across all polynomials.

A skeleton `fpm` project with the `polyroots-fortran` library dependency is at `/app/fortran_bench/`. The environment provides `gfortran`, `fpm`, and LAPACK/BLAS.

Write the audit report to `/app/audit.json`:

```json
{
  "defective_polynomials": ["<name>", ...],
  "correct_polynomials": ["<name>", ...],
  "defects": {
    "<name>": {"type": "<defect_category>", "detail": "<explanation>"}
  },
  "corrected_roots": {
    "<name>": [{"re": <float>, "im": <float>}, ...]
  },
  "algorithm_comparison": {
    "<algorithm>": {
      "<name>": {"max_backward_error": <float>, "num_accurate_roots": <int>}
    }
  },
  "best_algorithm": "<algorithm>"
}
```

All six polynomials must appear classified as either defective or correct. The corrected root count per polynomial must equal its degree. The algorithm comparison must cover at least three algorithms, each with data for all six polynomials.