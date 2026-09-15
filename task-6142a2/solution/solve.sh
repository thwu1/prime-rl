#!/bin/bash

# Install solution dependencies
pip3 install duckdb==1.1.3 -q

# Step 1: Use jq to extract validation manifest from hub config
jq '{
  required_quantiles: .rounds[0].model_tasks[0].output_type.quantile.output_type_id_params.required | sort,
  value_minimum: .rounds[0].model_tasks[0].output_type.quantile.value.minimum,
  required_horizons: .rounds[0].model_tasks[0].task_ids.horizon.required | sort,
  required_locations: .rounds[0].model_tasks[0].task_ids.location.required | sort
}' /app/hub-config/tasks.json > /app/output/validation_manifest.json

# Step 2: Run main evaluation pipeline (reads mixed formats, writes CSV + SQLite)
cd /app
python3 /solution/solution.py

# Step 3: Use DuckDB CLI to export summary.parquet from results.db
duckdb -c "
LOAD sqlite_scanner;
ATTACH '/app/output/results.db' AS results (TYPE SQLITE);
COPY (
    SELECT e.model_id, e.mean_wis, e.relative_wis, w.weight
    FROM results.ensemble_evaluation e
    LEFT JOIN results.ensemble_weights w ON e.model_id = w.model_id
    ORDER BY e.mean_wis ASC
) TO '/app/output/summary.parquet' (FORMAT PARQUET);
"
