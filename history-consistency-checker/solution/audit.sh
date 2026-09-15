#!/bin/bash

set -e

mkdir -p /app/output/graphs

# Create SQLite database with required schema
sqlite3 /app/output/audit.db "CREATE TABLE IF NOT EXISTS results (history_name TEXT PRIMARY KEY, history_type TEXT, result_json TEXT, pass INTEGER);"

for hist in /app/histories/*.json; do
    name=$(basename "$hist" .json)
    htype=$(jq -r '.type' "$hist")

    # Run checker
    result=$(python3 /app/checker.py "$hist")

    # For transactional histories, generate DOT dependency graph via jq
    if [ "$htype" = "transactional" ]; then
        jq -r '
            "digraph G {",
            "  rankdir=LR;",
            "  node [shape=box];",
            (.transactions[] | select(.status == "committed") |
                "  \"T\(.id)\" [label=\"T\(.id)\"];"),
            (.transactions[] | select(.status == "committed") |
                .id as $t | .operations[] |
                if .f == "write" then
                    "  \"T\($t)\" -> \"\(.key)\" [label=\"w(\(.value))\"];"
                elif .f == "read" then
                    "  \"\(.key)\" -> \"T\($t)\" [label=\"r(\(.value))\"];"
                else empty end),
            "}"
        ' "$hist" > "/app/output/graphs/${name}.dot"

        dot -Tsvg "/app/output/graphs/${name}.dot" -o "/app/output/graphs/${name}.svg"
    fi

    # Determine pass/fail
    if [ "$htype" = "register" ]; then
        pass_int=$(echo "$result" | jq 'if .linearizable then 1 else 0 end')
    else
        pass_int=$(echo "$result" | jq 'if (.anomalies | length) == 0 then 1 else 0 end')
    fi

    # Store result in SQLite
    escaped=$(echo "$result" | sed "s/'/''/g")
    sqlite3 /app/output/audit.db "INSERT OR REPLACE INTO results VALUES ('${name}', '${htype}', '${escaped}', ${pass_int});"
done
