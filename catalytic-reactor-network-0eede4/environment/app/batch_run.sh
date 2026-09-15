#!/bin/bash
# Batch processing script for catalytic reactor rate calculations
# Uses jq for JSON manipulation and catreactor.py for computation

set -euo pipefail

INPUT_FILE="${1:?Usage: batch_run.sh <input.json> <output.json>}"
OUTPUT_FILE="${2:?Usage: batch_run.sh <input.json> <output.json>}"

WORK_DIR=$(mktemp -d)
trap "rm -rf $WORK_DIR" EXIT

# Count number of cases
N_CASES=$(jq '.cases | length' "$INPUT_FILE")

# Process each case
RESULTS="[]"
for i in $(seq 0 $((N_CASES - 1))); do
    # Extract case input
    jq ".cases[$i].input" "$INPUT_FILE" > "$WORK_DIR/case_${i}.json"

    # Run catreactor rate subcommand
    python3 /app/catreactor.py rate "$WORK_DIR/case_${i}.json" "$WORK_DIR/out_${i}.json"

    # Extract result and append to results array
    RATE=$(jq '.results' "$WORK_DIR/out_${i}.json")
    RESULTS=$(echo "$RESULTS" | jq --argjson r "$RATE" --argjson idx "$i" '. + [{"case": $idx, "rate": $r}]')
done

# Write final aggregated output
echo "$RESULTS" | jq '.' > "$OUTPUT_FILE"
