#!/bin/bash
# Corrected post-processing: merge and deduplicate violations
#

SQL="/app/sql_violations.json"
PY="/app/py_violations.json"
OUT="/app/violations.json"

# FIX: unique_by([.type, .rule]) instead of unique_by(.type)
jq -s 'add | unique_by([.type, .rule]) | sort_by(.type, .rule)' "$SQL" "$PY" > "$OUT"
