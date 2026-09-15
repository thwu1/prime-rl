A DOE ATS-5 SPARTA DSMC weak-scaling procurement study has been run across multiple node counts. Initial analysis using the provided reference pipeline (`awk`/`bc` in `/app/reference/sparta_fom.sh`) produced errors or unexpected results on some runs. Your task is to conduct a comprehensive audit and produce a corrected performance analysis using the installed toolchain.

## Environment

- `/app/data/logs/` — SPARTA simulation output logs from scaling and cross-validation runs
- `/app/data/manifest.json` — Declared run configurations (node counts, rank counts, file mappings)
- `/app/reference/sparta_fom.sh` — Reference FOM extraction pipeline using `awk` + `bc`
- `/app/reference/plot_scaling.gp` — Gnuplot template for scaling visualization
- `/app/reference/schema.sql` — SQLite schema for benchmark results database
- Installed tools: `gawk`, `bc`, `sqlite3`, `gnuplot`, `python3`

## Task

Investigate the benchmark data and reference shell pipeline. Run `/app/reference/sparta_fom.sh` against each log file and observe failures. Cross-reference the manifest against actual log file contents. Determine why the reference `awk`/`bc` pipeline fails or produces incorrect results on certain logs, and build a corrected analysis.

Compute the corrected ATS-5 FOM for each run. The ATS-5 FOM is the harmonic mean of per-timestep throughput (Mega-particle-steps/sec) from statistics rows where CPU time is strictly between 300 and 600 seconds, divided by the number of compute nodes (derived from MPI rank count at 112 ranks-per-node).

Store all parsed benchmark data and results in an SQLite database at `/app/benchmark.db`. Initialize the database using the provided schema at `/app/reference/schema.sql`, then populate the `runs`, `scaling_models`, and `audit_issues` tables with your findings.

Using the four scaling-series FOMs (`scaling_1` through `scaling_64`), fit two competing models to per-node FOM as a function of node count *p*:

- **Amdahl's law** (weak-scaling form): `FOM(p) = FOM_1 / (1 + f * (p - 1))`
- **Power-law**: `FOM(p) = a * p^(-b)`

Report fitted parameters and coefficient of determination (R²) for each model, computed in original FOM space. Identify which model better describes the observed scaling. Use the better model to predict per-node FOM at 256 nodes and compute parallel efficiency (`predicted_FOM_256 / FOM_at_1_node`).

Generate a scaling visualization at `/app/scaling_plot.png` using gnuplot. The plot must show measured FOM values and both fitted model curves on a log-scaled x-axis with labeled axes, a legend distinguishing measured data from each model, and grid lines. Use or adapt the template at `/app/reference/plot_scaling.gp`.

Cross-validate: predict the validation run's FOM at its actual node count (which must be determined from the log, not the manifest) and report the prediction error percentage.

Write `/app/report.json`:

```json
{
  "audit": {
    "data_issues": [
      {"run": "<run_name>", "issue_type": "<type>", "detail": "<description>"}
    ],
    "script_issues": [
      {"issue_type": "<type>", "detail": "<description>"}
    ]
  },
  "fom": {
    "scaling_1": <float>,
    "scaling_4": <float>,
    "scaling_16": <float>,
    "scaling_64": <float>,
    "validation": <float>
  },
  "scaling_models": {
    "amdahl": {
      "serial_fraction": <float>,
      "r_squared": <float>,
      "predicted_fom_256": <float>
    },
    "power_law": {
      "exponent": <float>,
      "coefficient": <float>,
      "r_squared": <float>,
      "predicted_fom_256": <float>
    },
    "best_model": "amdahl" | "power_law"
  },
  "cross_validation": {
    "actual_node_count": <int>,
    "predicted_fom": <float>,
    "actual_fom": <float>,
    "prediction_error_pct": <float>
  }
}
```