#!/bin/bash
# Post-process pipeline: merge SQL-extracted and Python-detected violations
# Deduplicate by (type, rule) pair and sort for deterministic output

SQL="/app/sql_violations.json"
PY="/app/py_violations.json"
OUT="/app/violations.json"

jq -s 'add | unique_by(.type) | sort_by(.type, .rule)' "$SQL" "$PY" > "$OUT"
