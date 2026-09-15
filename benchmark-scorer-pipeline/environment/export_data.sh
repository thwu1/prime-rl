#!/bin/bash
# Export database tables in multiple formats for cross-tool analysis

mkdir -p /app/data/csv /app/data/ndjson

# CSV exports via sqlite3 CLI
sqlite3 -header -csv /app/benchmark.db "SELECT * FROM papers ORDER BY paper_id" > /app/data/csv/papers.csv
sqlite3 -header -csv /app/benchmark.db "SELECT * FROM snippets ORDER BY snippet_id" > /app/data/csv/snippets.csv
sqlite3 -header -csv /app/benchmark.db "SELECT * FROM models ORDER BY model_id" > /app/data/csv/models.csv
sqlite3 -header -csv /app/benchmark.db "SELECT * FROM results ORDER BY model_id, snippet_id" > /app/data/csv/results.csv
sqlite3 -header -csv /app/benchmark.db "SELECT * FROM v_paper_complexity ORDER BY paper_id" > /app/data/csv/paper_complexity.csv
sqlite3 -header -csv /app/benchmark.db "SELECT * FROM v_model_paper_contamination ORDER BY model_id, paper_id" > /app/data/csv/contamination.csv

# NDJSON exports via sqlite3 JSON mode + jq
sqlite3 -json /app/benchmark.db "SELECT * FROM v_results_detail ORDER BY model_id, snippet_id" | jq -c '.[]' > /app/data/ndjson/results_detail.ndjson
sqlite3 -json /app/benchmark.db "SELECT * FROM v_model_paper_contamination ORDER BY model_id, paper_id" | jq -c '.[]' > /app/data/ndjson/contamination.ndjson
sqlite3 -json /app/benchmark.db "SELECT * FROM v_paper_complexity ORDER BY paper_id" | jq -c '.[]' > /app/data/ndjson/paper_complexity.ndjson
