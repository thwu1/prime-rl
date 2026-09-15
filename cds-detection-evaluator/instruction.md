Build a multi-model evaluation and ranking pipeline for a LiDAR scene flow benchmark using DuckDB for data processing and a composite scoring methodology adapted from the Argoverse 2 detection challenge.

Ground truth annotations (Apache Feather) are at `/app/ground_truth/`, organized as `log_id/timestamp_ns.feather`. Four model submissions under `/app/submissions/` each use a different storage format and may require preprocessing — consult `/app/submissions/manifest.json`. One model's predictions are in the global reference frame and require ego-motion compensation using the per-sweep displacement data in `/app/ego_poses.json`. The per-point evaluation metrics are defined by the reference implementation at `/app/reference/scene_flow_eval.py`. The composite ranking methodology is described in `/app/scoring_protocol.md` and must be derived by studying the detection evaluation reference at `/app/reference/detection_eval.py`.

Produce:

**`/app/benchmark.duckdb`** — DuckDB database with a `point_metrics` table holding one row per valid evaluated point per model. Required columns: `model` (TEXT), `log_id` (TEXT), `timestamp_ns` (BIGINT), `class_name` (TEXT), `motion` (TEXT), `is_close` (BOOLEAN), `epe` (DOUBLE), `accuracy_strict` (DOUBLE), `accuracy_relaxed` (DOUBLE), `angle_error` (DOUBLE), `pred_dynamic` (BOOLEAN), `gt_dynamic` (BOOLEAN).

**`/app/leaderboard.json`** — Models ranked by CSFS descending:

```json
{"ranking": [{"rank": 1, "model": "...", "csfs": 0.0, "dynamic_iou": 0.0,
  "epe_3way": 0.0, "accuracy_strict_3way": 0.0, "accuracy_relaxed_3way": 0.0,
  "angle_error_3way": 0.0,
  "per_subset": {"Foreground/Dynamic/Close": {"EPE": 0.0, "Accuracy Strict": 0.0,
    "Accuracy Relaxed": 0.0, "Angle Error": 0.0}, ...},
  "per_class_motion": {"Foreground/Dynamic": {...}, ...}}, ...]}
```

Include only the 6 valid subsets and 3 valid class/motion groups (Background/Dynamic excluded). Round floats to 6 decimal places.