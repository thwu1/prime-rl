A statistical agency needs to release population data while satisfying zero-concentrated differential privacy (zCDP) guarantees. Build a pipeline at `/app/pipeline.py` that reads census population histograms and a disclosure avoidance configuration, then produces privatized synthetic histograms along with privacy accounting metadata.

The pipeline must be executable via `python3 /app/pipeline.py` and must work correctly on any valid configuration and dataset, not just the provided example.

## Inputs

`/app/config.json` specifies:
- `schema`: dimension names and sizes defining the histogram shape (product of sizes = total cells per histogram)
- `hierarchy`: a tree of geographic areas organized into named levels, with a root at the top
- `queries`: each query names a set of dimensions to marginalize (`sum_over_dims`) and carries a budget `proportion`
- `privacy`: total privacy budget `total_rho` (zCDP rho), a `bounded_dp_multiplier`, and per-level budget shares `level_proportions`
- `constraints`: multi-index positions designating structural zeros
- `seed`: integer for reproducible randomness

`/app/data/{geocode}.json` — true population histogram for each geography (flat integer array, row-major order over schema dimensions).

## Required Outputs (write to `/app/output/`)

**`sensitivities.json`** — For each query, report unbounded and bounded L1 and L2 sensitivity metrics:
```json
{"query_name": {"l1_unbounded": float, "l2_unbounded": float, "l1_bounded": float, "l2_bounded": float}}
```

**`budget.json`** — For each geographic level and query, report the allocated zCDP privacy budget `rho` and calibrated Gaussian noise scale `sigma`:
```json
{"level_name": {"query_name": {"rho": float, "sigma": float}}}
```

**`synthetic/{geocode}.json`** — Privatized histogram for every geography in the hierarchy (flat JSON array of integers).

## Constraints on Synthetic Output

All synthetic histograms must simultaneously satisfy:
- Non-negative integer values
- Correct number of cells matching the schema dimensions
- Total population at each geography equals the true total for that geography
- Children histograms sum cell-wise to their parent histogram
- Structural zero cells remain exactly zero
- Different random seeds must produce different synthetic outputs