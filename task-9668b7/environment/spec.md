# HLS Design Space Exploration Analyzer — Specification

## Overview

Build a design space exploration analyzer for HLS workflows that evaluates
configurations, identifies optimal tradeoffs, and quantifies the quality
of the resulting Pareto front.

## Input Files

- **YAML configuration** (`/app/dse_config.yaml`): DSE parameter space,
  dependency constraints, optimization objectives, and reference point.
- **Shared library** (`/app/libhls_cost.so`): compiled C library for
  evaluating HLS configurations. Interface defined in `/app/hls_cost.h`.

## Shared Library Interface

The library must be loaded and called from Python. Refer to `/app/hls_cost.h`
for the complete struct definitions and function prototypes.

Key integration notes:

- **Strategy mapping**: The `vivado_strategy` field in the C struct is an
  integer. Map YAML string values as: `"Default"` → 0,
  `"Performance_Explore"` → 1, `"Area_Explore"` → 2.
- **Boolean mapping**: C struct uses `int` (0 or 1) for boolean-typed
  YAML fields (`enable_pipeline`, `enable_dataflow`, `dsp_full_reg`).
- **Batch API**: `hls_evaluate_batch` accepts arrays of structs for
  efficient bulk evaluation.

## Required Analysis

### Configuration Expansion

Generate all valid configuration dictionaries from the cartesian product
of the YAML parameter space. Dependency constraints specify that certain
parameters only vary when a parent parameter matches a condition value;
otherwise the dependent parameter must equal its `default_when_inactive`
value and any combination assigning it a different value is invalid.

### Evaluation

Evaluate each valid configuration using the shared library to obtain PPA
metrics: `area_luts`, `latency_ns`, `power_mw`. Round each metric to
4 decimal places.

### Pareto Dominance and Ranking

**Dominance**: Point A *dominates* point B if A[obj] <= B[obj] for all
objectives and A[obj] < B[obj] for at least one. All objectives are
minimized.

**Pareto front**: The set of all non-dominated points (rank 1).

**Pareto ranking**: Assign an integer rank to every evaluated point.
Rank 1 is the Pareto front. For k > 1, rank k is the set of
non-dominated points among all points not yet assigned to ranks 1..k-1.
Ranks are 1-indexed and contiguous.

### Hypervolume Indicator

The hypervolume indicator H(S, r) of a point set S with reference point
r = (r1, r2, r3) equals the 3-dimensional Lebesgue measure (volume) of
the region dominated by at least one point in S and bounded by r:

    H(S, r) = volume( union over s in S of [s1,r1] x [s2,r2] x [s3,r3] )

where each interval [si, ri] is non-empty only when si < ri. Points with
any coordinate >= the corresponding reference coordinate contribute zero
volume.

Compute this for the rank-1 Pareto front using the reference point from
the YAML config.

### Exclusive Hypervolume Contribution

For each point p on the Pareto front:

    contribution(p) = H(S, r) - H(S \ {p}, r)

### Front Reduction

Given a target size K < |S|, produce a subset of size K. At each step,
remove the point with the smallest exclusive contribution, then recompute
all contributions for the remaining set before the next removal.

## CLI Interface

```
python3 /app/dse_analyzer.py --config /app/dse_config.yaml --output /app/results.json [--max-points K]
```

## Output JSON Schema

```json
{
  "total_configurations": "<int>",
  "num_pareto_optimal": "<int>",
  "num_ranks": "<int>",
  "pareto_front": [
    {
      "config": {},
      "metrics": {"area_luts": 0, "latency_ns": 0, "power_mw": 0},
      "contribution": 0.0
    }
  ],
  "hypervolume": 0.0,
  "reference_point": {"area_luts": 0, "latency_ns": 0, "power_mw": 0},
  "reduced_front": []
}
```

- `reduced_front` is only present when `--max-points` is specified and
  is less than `num_pareto_optimal`.

## Python API

The module must expose these importable functions:

- `expand_configurations(yaml_config: dict) -> list[dict]`
- `evaluate_all(configs: list[dict]) -> list[dict]`
  Each returned dict has keys `'config'` and `'metrics'`.
- `pareto_front(points: list[dict], objectives: list[str]) -> list[int]`
  Returns indices of non-dominated points.
- `non_dominated_sort(points: list[dict], objectives: list[str]) -> list[int]`
  Returns a rank (1-indexed) for each point.
- `hypervolume_3d(front_points: list[tuple], ref: tuple) -> float`
  Computes the 3D hypervolume indicator. Tuples are (obj1, obj2, obj3).
- `exclusive_contributions(front_points: list[tuple], ref: tuple) -> list[float]`
- `greedy_reduce(front_points: list[tuple], ref: tuple, max_k: int) -> list[int]`
  Returns indices into `front_points` to keep.
