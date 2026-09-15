# Benchmark Statistical Comparison Engine — Specification

## Overview

Build a command-line tool that compares two benchmark runs statistically and
produces a JSON report. Inspired by Linux `perf_event_open`-based benchmarking
tools that collect hardware performance counters across repeated executions.

**Constraint:** Only Python standard library modules (`math`, `random`, `json`,
`sys`, `os`) may be used. No `numpy`, `scipy`, `statsmodels`, or any other
external package.

## Input Format

Each benchmark file is JSON:

```json
{
  "label": "baseline",
  "command": "./benchmark --config base.cfg",
  "samples": [
    {
      "wall_time_ns": 5000000,
      "cpu_cycles": 15000000,
      "cache_misses": 5000,
      "peak_rss_bytes": 16500000
    }
  ]
}
```

Metrics to compare: `wall_time_ns`, `cpu_cycles`, `cache_misses`, `peak_rss_bytes`.

## Required Algorithms

### 1. Log-Gamma Function

Implement `log_gamma(x)` using the Lanczos approximation with the reflection
formula for x < 0.5. Must be accurate to at least 10 significant digits for
x > 0.

### 2. Regularized Incomplete Beta Function

Implement `regularized_incomplete_beta(x, a, b)` — I_x(a, b).

Use the continued fraction expansion with Lentz's modified method. Apply the
symmetry relation I_x(a,b) = 1 - I_{1-x}(b,a) when x > (a+1)/(a+b+2) for
better convergence.

Must handle boundaries: I_0(a,b) = 0, I_1(a,b) = 1.

### 3. Student's t-Distribution CDF

Implement `t_cdf(t_val, df)` using the relationship to the incomplete beta:

- For t >= 0: CDF(t) = 1 - 0.5 * I_x(df/2, 1/2) where x = df/(df + t²)
- For t < 0:  CDF(t) = 0.5 * I_x(df/2, 1/2)

### 4. Normal CDF and Inverse Normal CDF

- `normal_cdf(x)`: Use `math.erfc`: Φ(x) = 0.5 * erfc(-x/√2)
- `inverse_normal_cdf(p)`: Use a rational approximation (e.g.,
  Beasley-Springer-Moro or Peter Acklam's algorithm). Accurate to at least
  6 significant digits for 1e-8 < p < 1-1e-8.

### 5. Welch's t-Test

Implement `welch_ttest(sample1, sample2)` → (t_statistic, p_value, df).

- t = (mean1 - mean2) / sqrt(var1/n1 + var2/n2)
- Welch-Satterthwaite df = (var1/n1 + var2/n2)² / ((var1/n1)²/(n1-1) + (var2/n2)²/(n2-1))
- Two-tailed p-value via `t_cdf`

Edge cases:
- Both zero variance, equal means → (0.0, 1.0, 1.0)
- Both zero variance, different means → (±inf, 0.0, 1.0)
- One zero variance → skip that term in the df denominator

### 6. Tukey's Fences Outlier Detection

Implement `tukey_fences(data)` → (outlier_indices, clean_data).

- Compute Q1, Q3 using the exclusive median-of-halves method
- IQR = Q3 - Q1
- Outlier if value < Q1 - 1.5*IQR or value > Q3 + 1.5*IQR
- Return indices into original (unsorted) data
- For n < 4, return no outliers

### 7. BCa Bootstrap Confidence Interval

Implement `bca_bootstrap_ci(sample1, sample2, alpha=0.05, n_bootstrap=10000, seed=42)` → (ci_lower, ci_upper).

For the difference in means (mean(sample1) - mean(sample2)):

1. Generate n_bootstrap resamples (with replacement), compute bootstrap differences
2. Bias correction: z0 = Φ⁻¹(proportion of bootstrap diffs < observed diff)
3. Acceleration via jackknife: drop each observation from sample1 and sample2 in turn,
   recompute statistic, then a = Σ(θ̄ - θᵢ)³ / (6 * (Σ(θ̄ - θᵢ)²)^{3/2})
4. Adjusted percentiles: α₁ = Φ(z0 + (z0 + z_α)/(1 - a*(z0 + z_α))), similarly α₂
5. Return bootstrap distribution quantiles at α₁ and α₂

### 8. Cliff's Delta

Implement `cliffs_delta(sample1, sample2)` → float in [-1, 1].

δ = (#{x > y} - #{x < y}) / (n1 * n2)

Ties contribute 0 to both counts.

### 9. Holm-Bonferroni Correction

Implement `holm_bonferroni(p_values)` → adjusted p-values (same order as input).

1. Sort p-values, keeping original indices
2. For rank k (0-indexed): adj_k = min(1.0, p_k * (m - k))
3. Enforce monotonicity: adj_k = max(adj_k, adj_{k-1})
4. Return in original order

### 10. Effect Size Classification

Using Vargha & Delaney thresholds on |Cliff's delta|:
- < 0.147: "negligible"
- < 0.33: "small"
- < 0.474: "medium"
- >= 0.474: "large"

### 11. Metric Verdict

- p_adjusted >= alpha → "no_change"
- p_adjusted < alpha and pct_change > 0 → "regression"
- p_adjusted < alpha and pct_change < 0 → "improvement"

### 12. Quartile Computation

Use the exclusive method:
- Sort data
- Q1 = median of lower half (first n//2 elements)
- Q3 = median of upper half (last n - (n+1)//2 elements)
- Median of even-length array = average of two middle elements

## Output Format

```json
{
  "baseline_label": "baseline",
  "candidate_label": "candidate",
  "alpha": 0.05,
  "metrics": {
    "<metric_name>": {
      "baseline": {
        "mean": float,
        "median": float,
        "std_dev": float,
        "q1": float,
        "q3": float,
        "n": int,
        "outlier_indices": [int]
      },
      "candidate": { ... same structure ... },
      "comparison": {
        "mean_diff": float,
        "pct_change": float,
        "welch_t": float,
        "welch_df": float,
        "p_value_raw": float,
        "p_value_adjusted": float,
        "cliffs_delta": float,
        "effect_size_class": str,
        "bootstrap_ci_lower": float,
        "bootstrap_ci_upper": float,
        "verdict": str
      }
    }
  },
  "overall_verdict": str
}
```

- `mean_diff` = candidate_mean - baseline_mean
- `pct_change` = (candidate_mean - baseline_mean) / baseline_mean * 100
- Statistical tests use clean data (outliers removed via Tukey's Fences)
- `overall_verdict`: "regression" if any metric regressed; "improvement" if any
  improved and none regressed; "no_change" otherwise

## CLI Usage

```
python3 benchmark_compare.py <baseline.json> <candidate.json> <output.json>
```
