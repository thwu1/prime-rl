#!/bin/bash

cd /app

# Explore database schema and views using sqlite3 CLI
sqlite3 /app/benchmark.db ".schema"
sqlite3 /app/benchmark.db "SELECT sql FROM sqlite_master WHERE type='view';"

# Query contamination boundary semantics with sqlite3 CLI
sqlite3 /app/benchmark.db "SELECT * FROM v_model_paper_contamination ORDER BY model_id, paper_id;"

# Explore data exports using jq (NDJSON) and mlr (CSV)
jq -s 'group_by(.model_id) | .[] | {model: .[0].model_id, safe: [.[] | select(.safety_status=="safe")] | length, contaminated: [.[] | select(.safety_status=="contaminated")] | length}' /app/data/ndjson/contamination.ndjson
mlr --csv stats1 -a count,sum,mean -f total_loc /app/data/csv/paper_complexity.csv
mlr --csv --opprint cat /app/data/csv/models.csv

# Cross-validate LOC distribution using csvsql
csvsql --query "SELECT paper_id, COUNT(*) as n_snippets, SUM(lines_of_code) as total_loc FROM snippets GROUP BY paper_id ORDER BY total_loc DESC" /app/data/csv/snippets.csv

# Compare JSON prototype outputs using jq
make compare

# Compare Beta CSV prototype outputs using mlr
make compare-beta

# Cross-format reconciliation to identify correct approaches per metric
make reconcile

# Diff prototype source code to understand design choice differences
diff /app/pipelines/alpha.py /app/pipelines/beta.py || true
diff /app/pipelines/beta.py /app/pipelines/gamma.py || true

# Review the buggy draft output with jq
make show-draft

# Synthesize and run the correct pipeline
python3 /solution/solver.py

# Validate output structure using multi-tool validation pipeline
make validate
