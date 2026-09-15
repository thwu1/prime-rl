#!/bin/bash
# Fixed FIMI mining pipeline entry point
#

MODE="$1"
INPUT="$2"
MIN_SUP="$3"
OUTPUT="${4:-}"

if [ -z "$MODE" ] || [ -z "$INPUT" ] || [ -z "$MIN_SUP" ]; then
    echo "Usage: fim <mode> <input_file> <min_support> [output_file]" >&2
    exit 1
fi

DB_PATH="/app/results.db"

# FIX: Initialize database if it doesn't exist
if [ ! -f "$DB_PATH" ]; then
    sqlite3 "$DB_PATH" < /app/schema/results.sql
fi

# FIX: Detect non-standard format by checking file content
needs_normalization() {
    local file="$1"
    head -20 "$file" | grep -qP '[|,#]'
    return $?
}

MINING_INPUT="$INPUT"
if needs_normalization "$INPUT"; then
    NORM_DIR="/app/data/normalized"
    mkdir -p "$NORM_DIR"
    BASENAME=$(basename "$INPUT" | sed 's/\.[^.]*$//')
    MINING_INPUT="${NORM_DIR}/${BASENAME}.dat"
    # FIX: Correct AWK script filename
    awk -f /app/lib/normalize.awk "$INPUT" > "$MINING_INPUT"
fi

# Run mining
MINE_ARGS=("$MODE" "$MINING_INPUT" "$MIN_SUP")
if [ -n "$OUTPUT" ]; then
    OUTDIR=$(dirname "$OUTPUT")
    [ -n "$OUTDIR" ] && mkdir -p "$OUTDIR"
    MINE_ARGS+=("$OUTPUT")
fi

STDOUT=$(python3 /app/lib/miner.py "${MINE_ARGS[@]}")
MINE_EXIT=$?

if [ $MINE_EXIT -ne 0 ]; then
    echo "$STDOUT" >&2
    exit $MINE_EXIT
fi

echo "$STDOUT"

# Store results in SQLite
TOTAL=$(echo "$STDOUT" | head -1)
PER_LENGTH_JSON=$(echo "$STDOUT" | tail -n +2 | python3 -c "
import sys, json
counts = [int(line.strip()) for line in sys.stdin if line.strip()]
print(json.dumps(counts))
")

# FIX: Properly quote $PER_LENGTH_JSON in INSERT
sqlite3 "$DB_PATH" "INSERT INTO mining_results (job_id, dataset, mode, min_support, total_itemsets, per_length_counts) VALUES ('$(date +%s%N)', '$INPUT', '$MODE', $MIN_SUP, $TOTAL, '$PER_LENGTH_JSON');"

exit 0
