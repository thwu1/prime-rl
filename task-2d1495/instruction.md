A model-reduction pipeline at `/app/pipeline/` crashed during execution. It processes matrices from a simulation workflow, computing compact representations under a shared rank budget.

The pipeline stores its matrix registry, processing configuration, and execution logs in a SQLite database (`pipeline.db`). Matrix data uses mixed storage formats: some matrices are in HDF5 files (`.h5`), others are raw binary (`.dat`). Use `sqlite3` to query the database schema and tables, `h5dump`/`h5ls` to inspect HDF5 dataset structure and attributes, and `jq` to parse JSON blobs in the execution log's `details` column. Cross-reference file sizes against registry entries to diagnose data integrity issues.

Investigate the pipeline directory to diagnose all failures and data integrity issues. The database registry has multiple errors, and the data directory may contain files not referenced in the registry. You must identify and correct all discrepancies, then process every matrix present in the data directory.

Write `/app/results.json` with the following structure:

```json
{
  "matrices": {
    "<name>": {
      "shape": [<rows>, <cols>],
      "dtype": "<storage data type>",
      "frobenius_norm": <float>,
      "numerical_rank": <int>,
      "allocated_rank": <int>,
      "svd_relative_error": <float>,
      "cur_relative_error": <float>,
      "top_5_singular_values": [<5 floats, decreasing>]
    }
  },
  "rank_allocation": {
    "budget": <int>,
    "total_allocated": <int>,
    "total_squared_svd_error": <float>
  }
}
```

Each key under `matrices` is the data filename without extension. All numerical computations use float64 arithmetic regardless of storage format.

- `numerical_rank`: count of singular values strictly exceeding `relative_tolerance * sigma_max`, using the tolerance from `pipeline_config` table in `pipeline.db`.
- `allocated_rank`: per-matrix ranks that minimize total squared Frobenius approximation error across all matrices, subject to the `rank_budget` constraint from `pipeline_config`.
- `svd_relative_error`: relative Frobenius error of the best rank-k approximation at allocated rank k, i.e. the tail singular value norm divided by the full Frobenius norm.
- `cur_relative_error`: relative Frobenius error of the CUR skeleton approximation at the allocated rank, with columns and rows selected by their statistical leverage scores computed at that rank.
- `top_5_singular_values`: the 5 largest singular values in non-increasing order.
- `total_squared_svd_error`: the minimized objective — the sum of squared Frobenius approximation errors across all matrices.