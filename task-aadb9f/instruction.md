A CUDA kernel occupancy prediction model at `/app/model.py` reads GPU architecture specifications from `/app/specs/` and kernel resource profiles from `/app/kernels/` to predict how many thread blocks can co-reside on a streaming multiprocessor (SM).

The model produces incorrect occupancy predictions for several configurations. Hardware profiling measurements in `/app/profiling/measurements.db` (table: `measurements`) provide ground-truth data. Discrepancies originate from defects in both the model implementation and the architecture specification data files. All issues must be identified and corrected.

Five optimization proposals in `/app/proposals.json` describe kernel parameter modifications whose impact on occupancy must be evaluated. Eight workloads in `/app/workloads.json` require correct predictions from the fixed model.

The corrected model must also expose a function `find_optimal_block_size(arch, kernel)` that returns the block size (must be a multiple of the architecture's warp size) maximizing occupancy. Ties: prefer more active blocks per SM, then smaller block size. If no valid block size exists, return `{"error": "no_valid_configuration"}`. Return dict keys: `optimal_block_size`, `active_blocks_per_sm`, `occupancy`, `limiting_resource`.

Write all results to `/app/results.json` conforming to the schema below.

## Output schema for `/app/results.json`

```json
{
  "diagnostics": [
    {"file": "<relative path from /app/>", "issue": "<description>", "fix": "<correction applied>"}
  ],
  "predictions": [
    {
      "workload_id": 1, "architecture": "...", "kernel": "...", "block_size": 256,
      "active_blocks_per_sm": 6, "active_warps_per_sm": 48,
      "occupancy": 0.75, "limiting_resource": "registers"
    }
  ],
  "optimization_evaluations": [
    {
      "proposal_id": 1, "verdict": "<improves|neutral|degrades|invalid>",
      "original_occupancy": 0.625, "proposed_occupancy": 1.0,
      "explanation": "..."
    }
  ],
  "optimal_configurations": [
    {
      "architecture": "...", "kernel": "...",
      "optimal_block_size": 64, "active_blocks_per_sm": 32,
      "occupancy": 1.0, "limiting_resource": "warps"
    }
  ]
}
```

The `diagnostics` array must list every code bug and data error found. The `predictions` array must contain one entry per workload ordered by `workload_id`. The `optimization_evaluations` array must have one entry per proposal ordered by `proposal_id`, with verdict one of `improves`, `neutral`, `degrades`, or `invalid`. For invalid entries, use `"error": "invalid_configuration"` and `"reason": "..."` instead of occupancy fields. The `optimal_configurations` array must contain entries for these kernel-architecture pairs: (`reduce_warp`, `volta`), (`fft_radix`, `ampere`), (`stencil_3d`, `hopper`).