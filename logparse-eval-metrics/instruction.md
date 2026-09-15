Raw log files from three distributed systems (HDFS, Apache, Linux) are at `/app/logs/{HDFS,Apache,Linux}.log`. Human-annotated ground truth CSVs (columns: `LineId,Content,EventId,EventTemplate`) are at `/app/ground_truth/{HDFS,Apache,Linux}.csv`. System metadata — log format strings and preprocessing regex patterns — is in `/app/config/systems.json`. Formal definitions of the four Loghub-2.0 accuracy metrics are in `/app/specs/metrics.md`. Template normalization rules are in `/app/specs/post_processing.md`.

Build a log parsing evaluation framework that, for each system, extracts structured content from raw log lines according to the system's format specification, discovers event templates by abstracting variable tokens to `<*>`, evaluates parsing quality against ground truth using all four metrics, and quantifies the effect of applying template normalization to both parsed and ground truth templates before re-evaluation.

Your evaluation module at `/app/evaluation/evaluate.py` must expose:
- `compute_ga_fga(gt_series, parsed_series)` → `(GA, FGA)` tuple of floats
- `compute_pa(gt_series, parsed_series)` → PA float
- `compute_fta(gt_series, parsed_series)` → FTA float

(Parameters are row-aligned `pd.Series` of template strings.)

Your normalization module at `/app/evaluation/post_process.py` must expose:
- `correct_template(template)` → corrected template string

Required outputs:
- `/app/results/parsed_{HDFS,Apache,Linux}.csv` — columns: `LineId,Content,EventId,EventTemplate` (2000 rows each)
- `/app/results/metrics_raw.csv` — columns: `System,GA,FGA,PA,FTA` (4 decimal places)
- `/app/results/metrics_corrected.csv` — same schema, after normalization applied to both parsed and ground truth templates
- `/app/results/improvement.csv` — columns: `System,GA_delta,FGA_delta,PA_delta,FTA_delta` (corrected minus raw, 4 decimal places)

Accuracy thresholds: HDFS raw GA > 0.20; Apache raw GA > 0.20; Linux raw GA > 0.05; HDFS corrected GA > 0.65; Apache corrected GA > 0.90; normalization must improve Apache GA over raw; HDFS PA must improve after normalization.