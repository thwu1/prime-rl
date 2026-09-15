#!/bin/bash
# Ingest evaluation data into SQLite database from JSON files
# Usage: ingest.sh <db_path> <data_dir>

DB="$1"
DATA_DIR="$2"

if [ -z "$DB" ] || [ -z "$DATA_DIR" ]; then
    echo "Usage: ingest.sh <db_path> <data_dir>" >&2
    exit 1
fi

# Ingest eval set metadata
jq -r '
  .eval_sets | to_entries[] |
  "INSERT OR REPLACE INTO eval_sets VALUES (\"\(.key)\", \"\(.value.description)\", \"\(.value.generator)\");"
' "$DATA_DIR/ground_truth.json" | sqlite3 "$DB"

# Ingest ground truth labels
jq -r '
  .eval_sets | to_entries[] | .key as $set |
  .value.labels | to_entries[] |
  "INSERT OR REPLACE INTO ground_truth VALUES (\"\($set)\", \"\(.key)\", \"\(.value.source)\", \(.value.human_believability));"
' "$DATA_DIR/ground_truth.json" | sqlite3 "$DB"

# Ingest prediction files
for pred_file in "$DATA_DIR"/predictions/*.json; do
    stem=$(basename "$pred_file" .json)

    # Insert submission metadata
    jq -r '
      "INSERT OR REPLACE INTO submissions (file_stem, team, docker_id, eval_set, execution_time) VALUES (\"'"$stem"'\", \"\(.team)\", \"\(.docker_id)\", \"\(.input)\", \(.execution_time));"
    ' "$pred_file" | sqlite3 "$DB"

    # Insert individual predictions
    jq -r '
      .prediction_list[] |
      "INSERT OR REPLACE INTO predictions VALUES (\"'"$stem"'\", \"\(.statement_id)\", \(.ai_likelihood_score), \(.believability));"
    ' "$pred_file" | sqlite3 "$DB"
done

echo "Ingestion complete"
