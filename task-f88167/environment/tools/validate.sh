#!/bin/bash
# Sokoban solution validation pipeline
# Reads solutions from database, validates against levels, produces JSON report

python3 /app/tools/validate_runner.py /app/sokoban.db /app/config.json | jq '.' > /app/report.json

ALL_PASS=$(jq -r '.all_passed' /app/report.json)
if [ "$ALL_PASS" = "true" ]; then
    echo "All levels passed validation." >&2
    exit 0
else
    echo "Validation failures detected:" >&2
    jq -r '.results[] | select(.status == "fail") | "  Level \(.level_id): \(.reason)"' /app/report.json >&2
    exit 1
fi
