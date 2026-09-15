#!/usr/bin/env bash

cd /app

# Clear any previous (broken) ingestion attempts
sqlite3 /app/submissions.db "DELETE FROM survival;"

# Ingest survival data from NDJSON files into SQLite.
# Fixes from buggy Makefile:
#   1. jq null handling: (if .risk_score == null then "NaN" ...) instead of (tostring)
#   2. Output format: @csv (not @tsv) to match sqlite3 .mode csv
for team in alpha beta gamma delta; do
    jq -r --arg t "$team" \
        '[$t, .patient_id, .event_time, .event_observed, (if .risk_score == null then "NaN" else (.risk_score | tostring) end)] | @csv' \
        /app/raw_predictions/${team}_survival.jsonl \
        > /tmp/${team}_survival.csv
    sqlite3 /app/submissions.db \
        ".mode csv" \
        ".import /tmp/${team}_survival.csv survival"
done

# Run the corrected evaluation engine
python3 /solution/evaluate.py
