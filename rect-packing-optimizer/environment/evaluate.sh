#!/bin/bash
# Evaluate the solver on all test cases.
# Builds the solver, runs on each case, scores, stores results in SQLite,
# and outputs structured JSON.
#
# Usage: bash /app/evaluate.sh
# Parse output: bash /app/evaluate.sh | jq '.cases[] | {case, score}'
# Query DB:     sqlite3 /app/results.db "SELECT * FROM summary;"

set -o pipefail

# Build
echo "=== Building solver ===" >&2
make -C /app >&2
if [ $? -ne 0 ]; then
    echo '{"error":"build_failed","cases":[],"summary":{"avg_score":0,"valid_cases":0,"total_cases":0}}'
    exit 1
fi

if [ ! -x /app/solver ]; then
    echo '{"error":"no_solver_binary","cases":[],"summary":{"avg_score":0,"valid_cases":0,"total_cases":0}}'
    exit 1
fi

TESTDIR="/app/testcases"
OUTDIR="/app/outputs"
DB="/app/results.db"

mkdir -p "$OUTDIR"

# Clear previous results
sqlite3 "$DB" "DELETE FROM results;" 2>/dev/null

json_cases=""
count=0

for input_file in "$TESTDIR"/case_*.txt; do
    name=$(basename "$input_file" .txt)
    output_file="$OUTDIR/${name}_out.txt"

    echo "=== $name ===" >&2

    # Run solver, capture wall-clock time
    start_ms=$(date +%s%3N)
    timeout 60 /app/solver < "$input_file" > "$output_file" 2>/dev/null
    exit_code=$?
    end_ms=$(date +%s%3N)
    elapsed=$((end_ms - start_ms))

    if [ $exit_code -ne 0 ]; then
        score=0
        status="FAILED_EXIT_${exit_code}"
        echo "  FAILED (exit code $exit_code, ${elapsed}ms)" >&2
    else
        result=$(python3 /app/scorer.py "$input_file" "$output_file" 2>&1)
        score=$(echo "$result" | grep "^Score:" | awk '{print $2}')
        status=$(echo "$result" | grep "^Status:" | cut -d' ' -f2-)
        if [ -z "$score" ]; then
            score=0
            status="SCORING_ERROR"
        fi
        echo "  Score: $score  Status: $status  Time: ${elapsed}ms" >&2
    fi

    # Store in SQLite
    sqlite3 "$DB" "INSERT OR REPLACE INTO results (case_name, score, status, solver_time_ms) VALUES ('$name', $score, '$status', $elapsed);"

    # Append to JSON array
    if [ $count -gt 0 ]; then json_cases="${json_cases},"; fi
    json_cases="${json_cases}{\"case\":\"${name}\",\"score\":${score},\"status\":\"${status}\",\"time_ms\":${elapsed}}"
    count=$((count + 1))
done

# Compute summary from DB
avg_score=$(sqlite3 "$DB" "SELECT COALESCE(CAST(AVG(score) AS INTEGER), 0) FROM results;")
valid=$(sqlite3 "$DB" "SELECT COUNT(*) FROM results WHERE status='OK';")
total=$(sqlite3 "$DB" "SELECT COUNT(*) FROM results;")

# Output JSON to stdout
echo "{\"cases\":[${json_cases}],\"summary\":{\"avg_score\":${avg_score},\"valid_cases\":${valid},\"total_cases\":${total}}}"
