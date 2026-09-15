A research team ran their MIB (Mechanistic Interpretability Benchmark) circuit evaluation pipeline and stored the results in `/app/mib.db`. An independent reproduction attempt produced different numbers. The pipeline code is at `/app/pipeline.py`.

The pipeline depends on a `CircuitSimulator` (`/app/simulator.py`, independently verified correct) that requires a configuration file. This file was not shipped — reconstruct `/app/simulator_config.json` from the `simulator_config` and `gt_weights` tables in the database, in the format expected by the simulator's constructor.

The team's incomplete methodology draft is at `/app/methods_draft.md`. It describes intended evaluation behavior conceptually but omits explicit formulas and contains unresolved editorial notes. A gzipped NDJSON execution trace from the last pipeline run is at `/app/pipeline_trace.ndjson.gz`. A known-correct reference evaluation for `eap_ig` on `ioi` is at `/app/reference_calibration.json`.

Raw importance scores are available in both the database (`importance_scores` table) and as gzipped JSONL under `/app/circuit_graphs/`. The database schema includes tables: `edges`, `importance_scores`, `ground_truth`, `simulator_config`, `gt_weights`, `pipeline_results`, `pipeline_metrics`.

Audit the pipeline against the methodology and trace data, identify all implementation bugs, and produce corrected results.

## Deliverables

1. `/app/simulator_config.json` — Reconstructed from database

2. `/app/bug_report.json`:
   ```json
   {"bugs": [{"location": "<where>", "description": "<what is wrong>", "fix": "<correct implementation>"}, ...]}
   ```

3. `/app/corrected_results.json`:
   ```json
   {
     "methods": {"<method>": {"<task>": {"faithfulnesses": [...], "weighted_edge_counts": [...], "cpr": float, "cmd": float, "cpr_log": float, "cmd_log": float}}},
     "auroc": {"<method>": {"<task>": float}},
     "ranking": {"by_cpr": [...], "by_cmd": [...]}
   }
   ```

Methods: `eap`, `eap_ig`, `act_patch`. Tasks: `ioi`, `mcqa`.