#!/bin/bash
# Validate reconciliation_report.json structure using jq
REPORT="/app/reconciliation_report.json"

if [ ! -f "$REPORT" ]; then
    echo "ERROR: $REPORT not found"
    exit 1
fi

if ! jq empty "$REPORT" 2>/dev/null; then
    echo "ERROR: Invalid JSON in $REPORT"
    exit 1
fi

ERRORS=0

if ! jq -e '.reconciliation_results' "$REPORT" > /dev/null 2>&1; then
    echo "ERROR: Missing .reconciliation_results"
    ERRORS=$((ERRORS + 1))
fi

for field in total_violations by_category violations; do
    if ! jq -e ".reconciliation_results.$field" "$REPORT" > /dev/null 2>&1; then
        echo "ERROR: Missing .reconciliation_results.$field"
        ERRORS=$((ERRORS + 1))
    fi
done

if ! jq -e '.reconciliation_results.total_violations | type == "number"' "$REPORT" > /dev/null 2>&1; then
    echo "ERROR: total_violations must be a number"
    ERRORS=$((ERRORS + 1))
fi

if ! jq -e '.reconciliation_results.violations | type == "array"' "$REPORT" > /dev/null 2>&1; then
    echo "ERROR: violations must be an array"
    ERRORS=$((ERRORS + 1))
fi

VIOLATION_COUNT=$(jq '.reconciliation_results.violations | length' "$REPORT")
for i in $(seq 0 $((VIOLATION_COUNT - 1))); do
    for field in category source_table source_id details; do
        if ! jq -e ".reconciliation_results.violations[$i].$field" "$REPORT" > /dev/null 2>&1; then
            echo "ERROR: violations[$i] missing $field"
            ERRORS=$((ERRORS + 1))
        fi
    done
done

BAD_CATS=$(jq -r '.reconciliation_results.by_category | to_entries[] | select(.value | type != "number") | .key' "$REPORT" 2>/dev/null)
if [ -n "$BAD_CATS" ]; then
    echo "ERROR: Non-integer values in by_category: $BAD_CATS"
    ERRORS=$((ERRORS + 1))
fi

SUM=$(jq '[.reconciliation_results.by_category | to_entries[].value] | add // 0' "$REPORT")
TOTAL=$(jq '.reconciliation_results.total_violations' "$REPORT")
if [ "$SUM" != "$TOTAL" ]; then
    echo "ERROR: by_category sum ($SUM) != total_violations ($TOTAL)"
    ERRORS=$((ERRORS + 1))
fi

if [ $ERRORS -gt 0 ]; then
    echo "FAILED: $ERRORS validation errors"
    exit 1
fi

echo "Schema validation passed"
exit 0
