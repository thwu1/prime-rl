Fix and complete the actuarial risk computation pipeline in `/app/risk_pipeline.R` so that executing `Rscript /app/run_pipeline.R` produces correct numerical results in `/app/results.json`. The `actuar` R package (or any actuarial library) must NOT be used in the solution.

The pipeline has four stages:

**Stage 1 — Severity Discretization**: `discretize_dist(cdf_func, from, to, step, method, lev_func=NULL)` discretizes a continuous CDF onto the arithmetic grid `{from, from+step, ..., to}`. Four methods must be supported: `"upper"` (forward differences), `"lower"` (backward differences with zero mass at `from`), `"rounding"` (midpoint method using half-step offsets), and `"unbiased"` (local first-moment matching via the limited expected value function `lev_func`).

**Stage 2 — Panjer Recursion**: `panjer_recursion(fx, dist, params, x_scale, tol, maxit)` computes the aggregate claim amount PMF using the recursive formula for frequency distributions in the (a,b,0) family. Must support `"poisson"` (with `params$lambda`) and `"geometric"` (with `params$prob`). Returns a list with `knots`, `pmf`, and `cdf` vectors.

**Stage 3 — Risk Measures**: `compute_var(knots, pmf, conf_level)` returns the Value-at-Risk, defined as the smallest knot where the cumulative distribution reaches or exceeds `conf_level`. `compute_cte(knots, pmf, conf_level)` returns the Conditional Tail Expectation E[S | S > VaR].

**Stage 4 — Beekman Ruin Bounds**: `beekman_ruin_bounds(severity_cdf, from, to, step, freq_prob)` computes lower and upper bounds on the infinite-time ruin probability psi(u) for u in {0, 5, 10, ..., 50}. The argument `severity_cdf` is the CDF of the integrated tail distribution H(x). Using complementary upper/lower discretizations of H and Panjer recursion with geometric frequency (parameter `freq_prob`), produce bounds on the compound geometric CDF F(u) and hence on psi(u) = 1 - F(u). Returns `list(lower=..., upper=...)` with length-11 vectors.

The driver `/app/run_pipeline.R` exercises these models:
- **Aggregate loss**: Poisson(lambda=10) frequency, Gamma(2,1) severity discretized on (0,22) with step 0.5 using the unbiased method
- **Ruin bounds**: Pareto(4,4) integrated tail distribution on (0,200) with step 1, geometric frequency with prob=1/6

`/app/results.json` schema:
```json
{
  "discretization": {"upper": [...], "lower": [...], "rounding": [...], "unbiased": [...]},
  "aggregate": {"mean": float, "cdf_at_10": float, "cdf_at_20": float, "cdf_at_30": float, "cdf_at_40": float},
  "risk_measures": {"var_90": float, "var_95": float, "var_99": float, "cte_90": float, "cte_95": float, "cte_99": float},
  "ruin_bounds": {"lower": [psi_L(u) for u in 0,5,...,50], "upper": [psi_U(u) for u in 0,5,...,50]}
}
```

All numerical values must match a reference oracle to within 1e-4 relative tolerance.
