#!/bin/bash
# Evaluation pipeline orchestrator
# Extracts data from SQLite, runs Python evaluator, post-processes with jq

set -e

DB="/app/benchmark.db"
PIPELINE_DIR="/app/pipeline"
OUTPUT_DIR="/app/output"

mkdir -p "$PIPELINE_DIR" "$OUTPUT_DIR"

# Read config from database
CUTOFF=$(sqlite3 "$DB" "SELECT value FROM config WHERE key='temporal_cutoff'")
TIMEOUT=$(sqlite3 "$DB" "SELECT value FROM config WHERE key='timeout_seconds'")
K_VALUES=$(sqlite3 "$DB" "SELECT value FROM config WHERE key='k_values'")

echo "Config: cutoff=$CUTOFF timeout=$TIMEOUT k_values=$K_VALUES"

# Export temporally-filtered problems to JSON
sqlite3 -json "$DB" \
    "SELECT * FROM problems WHERE release_date < '$CUTOFF'" \
    > "$PIPELINE_DIR/problems.json"

# Export predictions for filtered problems only
sqlite3 -json "$DB" \
    "SELECT p.* FROM predictions p INNER JOIN problems pr ON p.task_id = pr.task_id WHERE pr.release_date < '$CUTOFF'" \
    > "$PIPELINE_DIR/predictions.json"

NPROBS=$(jq length "$PIPELINE_DIR/problems.json")
NPREDS=$(jq length "$PIPELINE_DIR/predictions.json")
echo "Exported $NPROBS problems, $NPREDS predictions"

# Run Python evaluation pipeline
cd /app
python3 -m harness.evaluate \
    --problems "$PIPELINE_DIR/problems.json" \
    --predictions "$PIPELINE_DIR/predictions.json" \
    --timeout "$TIMEOUT" \
    --k-values "$K_VALUES" \
    --output "$PIPELINE_DIR/raw_results.json"

# Post-process: add config, sort models by pass@1, assign ranks
jq --arg cutoff "$CUTOFF" \
   --argjson timeout "$TIMEOUT" \
   --argjson k_values "$(echo "$K_VALUES" | jq -R 'split(",") | map(tonumber)')" \
   '{
     config: {
       temporal_cutoff: $cutoff,
       timeout_seconds: $timeout,
       k_values: $k_values
     },
     models: [.models | sort_by(.["pass@1"]) | to_entries[] | .value + {rank: (.key + 1)}]
   }' "$PIPELINE_DIR/raw_results.json" > "$OUTPUT_DIR/leaderboard.json"

echo "Leaderboard written to $OUTPUT_DIR/leaderboard.json"
