#!/bin/bash

# Batch validation pipeline — orchestrates yq, jq, and sqlite3
# Usage: /app/pipeline.sh <manifest_yaml> <output_db>

set -euo pipefail

MANIFEST="$1"
OUTPUT_DB="$2"
REPORT="${OUTPUT_DB%.db}.report.json"

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# ── Phase 1: Parse YAML manifest with yq ──
COUNT=$(yq '.configs | length' "$MANIFEST")

# ── Phase 2: Run validator on each config entry ──
for i in $(seq 0 $((COUNT - 1))); do
    CONFIG_PATH=$(yq ".configs[$i].path" "$MANIFEST")
    MODEL=$(yq ".configs[$i].model" "$MANIFEST")
    NUM_GPUS=$(yq ".configs[$i].num_gpus" "$MANIFEST")

    python3 /app/validator.py validate "/app/${CONFIG_PATH}" \
        --model "$MODEL" --num-gpus "$NUM_GPUS" > "$TMPDIR/result_${i}.json"
done

# ── Phase 3: Aggregate results with jq ──
jq -s '.' "$TMPDIR"/result_*.json > "$TMPDIR/merged.json"

jq '{
    total_configs: length,
    total_violations: ([.[].num_violations] | add // 0),
    clean_configs: ([.[] | select(.num_violations == 0)] | length),
    violation_summary: (
        [.[].violations[].rule] |
        group_by(.) |
        map({rule: .[0], count: length}) |
        sort_by(.rule) |
        sort_by(-(.count))
    )
}' "$TMPDIR/merged.json" > "$REPORT"

# ── Phase 4: Load results into SQLite database ──
rm -f "$OUTPUT_DB"

sqlite3 "$OUTPUT_DB" "
CREATE TABLE validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_file TEXT NOT NULL,
    model TEXT NOT NULL,
    num_gpus INTEGER NOT NULL,
    num_violations INTEGER NOT NULL
);
CREATE TABLE violations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id INTEGER NOT NULL,
    rule TEXT NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY (validation_id) REFERENCES validations(id)
);
"

# Generate SQL INSERT statements from JSON using jq, execute with sqlite3
jq -r '
    .[] |
    "INSERT INTO validations (config_file, model, num_gpus, num_violations) VALUES (" +
    (.config_file | @json) + ", " +
    (.model | @json) + ", " +
    (.num_gpus | tostring) + ", " +
    (.num_violations | tostring) + ");"
' "$TMPDIR/merged.json" > "$TMPDIR/load.sql"

# Generate violation inserts with validation_id references
for i in $(seq 0 $((COUNT - 1))); do
    VAL_ID=$((i + 1))
    jq -r --argjson vid "$VAL_ID" '
        .violations[] |
        "INSERT INTO violations (validation_id, rule, message) VALUES (" +
        ($vid | tostring) + ", " +
        (.rule | @json) + ", " +
        (.message | @json) + ");"
    ' "$TMPDIR/result_${i}.json"
done >> "$TMPDIR/load.sql"

sqlite3 "$OUTPUT_DB" < "$TMPDIR/load.sql"
