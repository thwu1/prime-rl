# Analysis of Speedup Aggregation Methods

## Background

When evaluating code optimization patches across multiple performance tests,
per-test speedups must be aggregated into a single overall metric. The choice
of aggregation method has significant implications for benchmark integrity.

Given *n* performance tests with per-test speedups `s_1, s_2, ..., s_n`
(where `s_i = T_baseline_i / T_optimized_i`), three candidate methods exist:

## Arithmetic Mean

```
AM(s) = (s_1 + s_2 + ... + s_n) / n
```

Simple to compute but highly sensitive to outliers. A patch achieving
speedups [0.1, 1000] across two tests gets AM = 500.05, vastly
overstating performance despite degrading one test by 10x.

## Geometric Mean

```
GM(s) = (s_1 * s_2 * ... * s_n) ^ (1/n)
```

More robust than arithmetic mean but still gameable. The same [0.1, 1000]
yields GM = sqrt(100) = 10, which still masks the severe regression.
An agent that makes one test 1000x faster while breaking another test
appears to have a 10x overall improvement.

## Harmonic Mean

```
HM(s) = n / (1/s_1 + 1/s_2 + ... + 1/s_n)
```

Dominated by the smallest values. For [0.1, 1000]:
HM = 2 / (10 + 0.001) = 0.2

This correctly penalizes the regression. The harmonic mean is bounded
by the minimum value and is widely used in systems benchmarking
literature for aggregating speedups (Jacob & Mudge 1995).

## Properties Summary

| Property            | Arithmetic | Geometric | Harmonic |
|---------------------|-----------|-----------|----------|
| Outlier resistance  | None      | Partial   | Strong   |
| Gaming resistance   | None      | Partial   | Strong   |
| Dominated by        | Largest   | —         | Smallest |
| AM >= GM >= HM      | Always    | Always    | Always   |

## Relative Comparison (Model vs Human)

When comparing a model's optimization against a human expert's optimization,
the natural formulation measures per-test relative speedup as:

```
relative_speedup_i = T_human_i / T_model_i
```

Where T_human_i is the runtime after the human expert's patch, and T_model_i
is the runtime after the model's patch, both measured on test i.

Interpretation:
- relative_speedup > 1: model optimization runs faster than human's
- relative_speedup < 1: model optimization runs slower than human's
- relative_speedup = 1: model matches human exactly

## Edge Cases

- If model time is 0 for a test (infinite speedup): the reciprocal
  contribution to the denominator sum is 0.
- If all model times are 0: the overall speedup is infinite.
- If human time is 0 but model time is nonzero (zero speedup on that
  test): the harmonic mean is 0.
