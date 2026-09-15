Perform multi-objective design space exploration on FPGA synthesis results from LLM-generated Verilog designs. Working directory: `/app/`.

## Inputs

- `/app/solutions_data.json` — Hierarchically structured synthesis results containing multiple LLM models, design categories, hardware modules, and per-solution pass/fail status with resource usage metrics. You must independently determine the nesting and field layout.
- `/app/resource_weights.json` — Cost weights for FPGA resource dimensions.

## Required Outputs

A solution is **valid** when its pass status (stripped of whitespace, case-insensitive) equals `"true"` and all resource dimensions named in the weights file are non-null integers. The **weighted cost** of a valid solution is the dot product of its resource values with the provided weights.

### `/app/validated_solutions.jsonl`

JSONL file (one compact JSON object per line) for every solution whose resource usage data includes an optimized resource sub-object. Each line must contain: `model`, `category`, `module`, `solution_index` (0-based position within the module's solutions array for that model), `pass_status`, `lut`, `ff`, `dsp`, `bram`, `io`. Resource dimensions absent from the optimized object appear as `null`.

### `/app/synthesis.db`

SQLite database with these relations:

- **Table `solutions`** — `model TEXT, category TEXT, module TEXT, solution_index INTEGER, pass_status TEXT, lut INTEGER, ff INTEGER, dsp INTEGER, bram INTEGER, weighted_cost REAL, is_valid INTEGER`. `weighted_cost` is `NULL` for invalid solutions.
- **Table or view `pareto_solutions`** — `module, model, solution_index, lut, ff, dsp, bram, weighted_cost`. The Pareto-optimal valid solutions per module pooled across all models, evaluated over the four resource dimensions.
- **Table or view `module_stats`** — `module, total_valid, pareto_count, best_cost, worst_cost`.

### `/app/dse_report.json`

```json
{
  "modules": {
    "<module>": {
      "total_passing": int,
      "pareto_frontier_size": int,
      "pareto_frontier": [{"model": str, "solution_index": int, "LUT": int, "FF": int, "DSP": int, "BRAM": int, "weighted_cost": float}],
      "rankings": [{"rank": int, "model": str, "solution_index": int, "weighted_cost": float, "is_pareto": bool}],
      "best_cost": float,
      "cost_spread": float,
      "hypervolume": float
    }
  },
  "model_summary": {
    "<model>": {
      "total_passing": int,
      "total_pareto": int,
      "pareto_fraction": float,
      "avg_weighted_cost": float,
      "avg_nre": float
    }
  }
}
```

- Pareto frontier entries sorted by `(weighted_cost, LUT, model)`.
- Rankings: all valid solutions sorted by `(weighted_cost, LUT, FF, model, solution_index)` ascending, 1-based consecutive ranks.
- `cost_spread`: difference between maximum and minimum weighted cost among valid solutions per module.
- `hypervolume`: hypervolume indicator over the four resource dimensions with per-module reference point of `(max_value + 1)` in each dimension across the module's valid solutions.
- `avg_nre`: mean Normalized Resource Efficiency across all valid solutions for that model, where a solution's NRE is the ratio of its module's best weighted cost to the solution's weighted cost.