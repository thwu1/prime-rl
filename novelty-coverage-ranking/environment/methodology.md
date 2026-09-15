# Novelty Coverage Evaluation Methodology

## Overview

This document describes the novelty coverage evaluation framework used to rank
coverage-guided fuzzers in a multi-benchmark, multi-trial experiment. The
methodology is derived from the SBFT 2025 fuzzing tool competition, which
introduced a Tversky-index-based novelty metric to reward fuzzers that discover
rare edges consistently.

## Definitions

- **F**: set of all fuzzers in the experiment; |F| = number of fuzzers
- **T**: number of independent trials per fuzzer per benchmark
- **coverage(f, b, t)**: set of edges covered by fuzzer f on benchmark b in trial t
  (using the final/maximum-timestamp snapshot)
- **edges(f, b)**: union of coverage(f, b, t) across all trials t

## Parameters

The Tversky-index parameters **alpha** and **beta** are stored in the experiment
database. Consult the experiment configuration to obtain their values.

## 1. Edge Rarity

For each edge **e** discovered by any fuzzer on a given benchmark:

- **D(e)** = { f in F : e in edges(f, b) } — the set of fuzzers whose coverage
  (union across trials) includes edge e
- **rarity(e)** = (|F| - |D(e)|) / (|F| - 1),  when |F| > 1

Rarity is 1.0 when only one fuzzer discovers the edge and 0.0 when all fuzzers
discover it.

## 2. Edge Consistency

For a given fuzzer **f** and edge **e** that f covers on benchmark **b**:

- **consistency(f, e)** = |{ t : e in coverage(f, b, t) }| / T

Consistency measures how reliably f rediscovers e across independent trials.

## 3. Novelty Score

For each edge e in edges(f, b), the contribution is:

    contribution(f, e) = rarity(e)^alpha * consistency(f, e)^beta

    novelty_score(f, b) = sum of contribution(f, e)    for all e in edges(f, b)

Also compute:

- **total_edges(f, b)** = |edges(f, b)|
- **unique_edges(f, b)** = |{ e : |D(e)| = 1 }| restricted to edges in edges(f, b)

## 4. Per-Trial Novelty (for statistical testing)

Per-trial scores are needed for pairwise statistical comparison between fuzzers.
These use rarity alone since consistency is inherently a cross-trial metric:

    trial_score(f, b, t) = sum of rarity(e)^alpha    for all e in coverage(f, b, t)

Rarity values are the same global rarity computed across all fuzzers and trials
(Section 1), not recomputed per trial.

## 5. Cross-Benchmark Ranking

Within each benchmark, rank fuzzers by **descending** novelty_score. Use
fractional ranking for ties: tied fuzzers receive the arithmetic mean of the
positions they span (e.g., two fuzzers tied for positions 2-3 each get rank 2.5).

Aggregate ranking:

- **mean_rank(f)** = arithmetic mean of f's ranks across all benchmarks
- Sort by ascending mean_rank (lowest = best)
- Break ties in mean_rank by descending total_novelty (sum of novelty_score
  across all benchmarks)

## 6. Pairwise Statistical Comparison

For each benchmark, for each pair of fuzzers **(i, j)** where i < j
alphabetically:

- Perform a **two-sided Mann-Whitney U test** on per-trial novelty scores
  (Section 4)
- Report the U statistic as **min(U1, U2)**

Apply **Benjamini-Hochberg FDR correction** across ALL pairwise tests from all
benchmarks combined:

1. Sort all raw p-values in ascending order
2. For the test at rank **k** (1-indexed) among **m** total tests:
   adjusted_p[k] = raw_p[k] * m / k
3. Enforce monotonicity by scanning from the largest rank downward:
   adjusted_p[k] = min(adjusted_p[k], adjusted_p[k+1])
4. Cap all values at 1.0

Report significance at alpha = 0.05 using corrected p-values.

## 7. Coverage Velocity

For each fuzzer-benchmark pair, at each time snapshot compute the mean number of
covered edges across all trials. Between consecutive snapshots:

    velocity = (mean_edges(t_{i+1}) - mean_edges(t_i)) / (t_{i+1} - t_i)
