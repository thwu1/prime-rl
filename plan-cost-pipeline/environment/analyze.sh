#!/bin/bash
set -euo pipefail


# CEB-style cardinality estimation evaluation pipeline
# Multi-stage: jq (cost computation) -> python (plan optimization) -> awk (statistics) -> python (report)

QUERY_DIR="/app/data/queries"
WORK_DIR="/app/work"
RESULT_DIR="/app/results"

mkdir -p "$WORK_DIR" "$RESULT_DIR"

# Clear previous q-error accumulation
> "$WORK_DIR/all_qerrors.txt"

echo "=== CEB Evaluation Pipeline ==="
echo "Query directory: $QUERY_DIR"
echo "Output directory: $RESULT_DIR"

query_count=0

# Stage 1: Compute edge costs and q-errors for each query using jq
for qfile in "$QUERY_DIR"/*.json; do
    [ -f "$qfile" ] || continue
    qname=$(basename "$qfile" .json)
    echo ""
    echo "Processing $qname..."

    # Run jq cost model filter to compute edge costs and q-errors
    jq -f /app/lib/costs.jq "$qfile" > "$WORK_DIR/${qname}_costs.json"

    # Collect q-errors for aggregation (pipe-separated: subplan|qerror)
    jq -r '.qerrors[] | "\(.subplan)|\(.qerror)"' "$WORK_DIR/${qname}_costs.json" > "$WORK_DIR/all_qerrors.txt"

    query_count=$((query_count + 1))
done

echo ""
echo "Computed costs for $query_count queries."

# Stage 2: Find optimal and estimated plans using python DP
for qfile in "$QUERY_DIR"/*.json; do
    [ -f "$qfile" ] || continue
    qname=$(basename "$qfile" .json)
    echo "Planning $qname..."

    python3 /app/lib/planner.py "$WORK_DIR/${qname}_plan.json" "$WORK_DIR/${qname}_costs.json"
done

# Stage 3: Compute Q-Error statistics using awk
echo "Aggregating Q-Error statistics..."
awk -f /app/lib/stats.awk "$WORK_DIR/all_qerrors.txt" > "$WORK_DIR/qerror_stats.json"

# Stage 4: Combine plan costs and stats into final report
echo "Generating report..."
python3 /app/lib/report.py "$WORK_DIR" "$RESULT_DIR/report.json"

echo "Done. Report at $RESULT_DIR/report.json"
