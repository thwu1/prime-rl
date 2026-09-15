The `/app/` directory contains a multi-stage optimal transport pipeline that uses a native C library for distance computation. Running `python3 /app/pipeline.py` should produce `/app/output/results.json` and exit 0. The pipeline currently fails or produces incorrect results.

Diagnose and fix all issues so the output has this schema and satisfies the constraints below:

```json
{
  "sinkhorn": {
    "transport_plan": [[...]], "cost": <float>, "iterations": <int>
  },
  "gromov_wasserstein": {
    "transport_plan": [[...]], "gw_distance": <float>, "iterations": <int>
  },
  "barycenter": {"weights": [...]}
}
```

**Sinkhorn transport**: non-negative entries; row sums equal source weights and column sums equal target weights from `/app/data/source.json` and `/app/data/target.json` (tolerance 1e-5); the reported cost must equal `sum(T * M)` where `M` is the pairwise squared Euclidean distance matrix recomputed from the raw point coordinates (relative tolerance 1%); cost must be strictly less than the cost of the independent coupling `np.outer(a, b)` evaluated against the same `M`; the solver must run more than 5 iterations.

**GW transport**: non-negative entries; row sums equal `p` and column sums equal `q` from `/app/data/graphs.json` (tolerance 1e-5); GW distance is positive and strictly less than the GW cost of the independent coupling `np.outer(p, q)` computed as `sum_{i,j,k,l} (C1[i,k] - C2[j,l])^2 * T[i,j] * T[k,l]`; the reported GW distance must be consistent with the transport plan (relative tolerance 5%).

**Barycenter**: non-negative entries summing to 1.0 (tolerance 1e-5); length matches the input distribution size from `/app/data/measures.json`; distribution is not approximately uniform; the maximum entry must be plausible relative to the input distributions (not a collapsed delta).

Input data is in `/app/data/`. Configuration is in `/app/config.json`.
