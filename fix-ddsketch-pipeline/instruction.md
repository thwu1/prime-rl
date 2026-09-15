A production metric aggregation pipeline at `/app/` computes streaming percentiles for distributed latency data across three service tiers (`web`, `batch`, `realtime`). Each tier has distinct accuracy and resource constraints defined in `/app/sla_config.json`.

The pipeline at `/app/pipeline.py` processes latency samples from a SQLite database at `/app/data/metrics.db`, groups them by time window and service tier, and uses the quantile sketch at `/app/sketch.py` to compute approximate percentile values. Currently the pipeline produces incorrect results.

Investigate the full system — the sketch data structure, its mathematical properties, and the pipeline's aggregation logic — and fix all defects so that the implementation produces correct, specification-conformant quantile estimates. Then determine per-tier sketch parameters that satisfy every tier's accuracy and resource constraints given each tier's actual data characteristics.

Write per-tier configuration to `/app/output/tier_config.json`:
```json
{"<tier>": {"alpha": <float>, "max_num_bins": <int>}, ...}
```

Run `/app/pipeline.py` to produce aggregated results at `/app/output/results.json`.