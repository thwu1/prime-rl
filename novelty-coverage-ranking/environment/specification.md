# FuzzBench Novelty Coverage Analysis — Specification

## Overview

You have raw coverage data from a fuzzer benchmarking experiment modeled on the
SBFT 2025 fuzzing tool competition. Multiple fuzzers were evaluated on multiple
benchmarks, each with multiple independent trials. Your task is to implement the
complete novelty coverage scoring and ranking pipeline.

## Data Location

All input data is at `/app/data/`. Output must be written to `/app/output/`.

## Data Format

### Directory Structure

```
/app/data/
├── meta.json
└── {fuzzer}/
    └── {benchmark}/
        └── trial_{NN}/
            └── coverage.cov
```

### meta.json

```json
{
  "fuzzers": ["fuzzer1", ...],
  "benchmarks": ["bench1", ...],
  "trials": <int>,
  "snapshots_seconds": [t1, t2, ...],
  "edge_space": <int>,
  "tversky_alpha": <float>,
  "tversky_beta": <float>
}
```

### Binary Coverage File Format (`.cov`)

All integers are **unsigned 32-bit little-endian**.

**Header** (16 bytes):

| Offset | Field          | Type     | Description                        |
|--------|----------------|----------|------------------------------------|
| 0      | magic          | char[4]  | `"FCOV"` (0x46 0x43 0x4F 0x56)    |
| 4      | version        | uint32   | Format version (must be `1`)       |
| 8      | edge_space     | uint32   | Total possible edges (N)           |
| 12     | num_snapshots  | uint32   | Number of time snapshots (S)       |

**Followed by S snapshot entries**, each:

| Offset | Field     | Type      | Description                             |
|--------|-----------|-----------|-----------------------------------------|
| 0      | timestamp | uint32    | Snapshot time in seconds                |
| 4      | num_edges | uint32    | Number of covered edges (K)             |
| 8      | edges     | uint32[K] | Covered edge indices, sorted ascending  |

Edges are zero-indexed integers in `[0, N)`.

---

## Metrics to Compute

### 1. Novelty Coverage Score

For each benchmark **b**, using the **final** (maximum timestamp) snapshot:

Let **F** = set of all fuzzers, **|F|** = number of fuzzers, **T** = number of
trials per fuzzer.

For each edge **e** discovered by any fuzzer in any trial:

- **D(e)** = set of fuzzers **f** where edge **e** appears in at least one of
  **f**'s trials
- **rarity(e)** = (|F| − |D(e)|) / (|F| − 1),  for |F| > 1

For each fuzzer **f ∈ D(e)**:

- **consistency(f, e)** = |{trial t : e ∈ coverage(f, b, t)}| / T
- **contribution(f, e)** = rarity(e)^α × consistency(f, e)^β

**novelty_score(f, b)** = Σ_{e : f ∈ D(e)} contribution(f, e)

Where α = `tversky_alpha` and β = `tversky_beta` from `meta.json`.

Also compute:

- **total_edges(f, b)** = |union of edges across all of f's trials on b|
- **unique_edges(f, b)** = number of edges where D(e) = {f} (only f covers this
  edge across all fuzzers)

### 2. Per-Trial Novelty Score (for statistical testing)

For each trial individually:

**trial_score(f, b, t)** = Σ_{e ∈ coverage(f, b, t)} rarity(e)^α

Note: per-trial scores use only rarity (not consistency), since consistency is
a cross-trial metric. The rarity values are the same as computed in Section 1
(global rarity across all fuzzers and trials).

### 3. Cross-Benchmark Ranking

For each benchmark **b**:

- Rank fuzzers by **novelty_score(f, b)** in descending order (highest score =
  rank 1)
- Handle ties with **fractional ranking**: tied fuzzers receive the average of
  the positions they span

Aggregate ranking:

- **mean_rank(f)** = mean of f's ranks across all benchmarks
- Final ranking: ascending **mean_rank** (lowest = best)
- Break ties in mean_rank by **descending total_novelty** (sum of novelty_score
  across all benchmarks)

### 4. Statistical Pairwise Comparison

For each benchmark, for each ordered pair of fuzzers **(i, j)** where
**i < j alphabetically**:

- Perform a **two-sided Mann-Whitney U test** on their per-trial novelty scores
  (Section 2)
- Report the **U statistic** (minimum of U₁, U₂) and **raw p-value**

Apply **Benjamini-Hochberg FDR correction** across ALL pairwise tests from all
benchmarks combined:

1. Sort all p-values in ascending order
2. For the test at rank **k** (1-indexed) among **m** total tests:
   adjusted_p[k] = raw_p[k] × m / k
3. Enforce monotonicity by scanning from the largest rank downward:
   adjusted_p[k] = min(adjusted_p[k], adjusted_p[k+1])
4. Cap all values at 1.0

Report significance at α = 0.05 (using corrected p-values).

### 5. Coverage Velocity

For each fuzzer-benchmark pair:

- At each snapshot time **t**, compute the **mean number of edges** covered
  across all trials
- Between consecutive snapshots **(t_i, t_{i+1})**:
  **velocity** = (mean_edges(t_{i+1}) − mean_edges(t_i)) / (t_{i+1} − t_i)

---

## Output Format

Write the following JSON files to `/app/output/`:

### novelty_scores.json

```json
{
  "<benchmark>": {
    "<fuzzer>": {
      "novelty_score": <float, 4 decimal places>,
      "total_edges": <int>,
      "unique_edges": <int>,
      "rank": <float, 1 decimal place>
    }
  }
}
```

### aggregate_ranking.json

```json
[
  {
    "fuzzer": "<name>",
    "mean_rank": <float, 2 decimal places>,
    "total_novelty": <float, 4 decimal places>,
    "per_benchmark_ranks": {"<benchmark>": <float, 1 decimal place>}
  }
]
```

Sorted by ascending `mean_rank`, ties broken by descending `total_novelty`.

### statistical_tests.json

```json
{
  "<benchmark>": {
    "<fuzzer_i>_vs_<fuzzer_j>": {
      "u_statistic": <float>,
      "p_value": <float, 6 decimal places>,
      "p_value_corrected": <float, 6 decimal places>,
      "significant": <bool>
    }
  }
}
```

Fuzzer pairs ordered alphabetically: `fuzzer_i < fuzzer_j`.

### coverage_velocity.json

```json
{
  "<benchmark>": {
    "<fuzzer>": {
      "snapshots": [
        {"time": <int>, "mean_edges": <float, 2 decimal places>}
      ],
      "velocities": [
        {"interval": [<t1>, <t2>], "edges_per_second": <float, 4 decimal places>}
      ]
    }
  }
}
```
