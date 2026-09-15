#!/bin/bash
# Normalize agent submissions: coerce string-encoded numbers for evaluation

SUBMISSIONS_DIR="/app/submissions"
OUT_DIR="/app/build/normalized"

mkdir -p "$OUT_DIR"

for f in "$SUBMISSIONS_DIR"/*.json; do
    agent=$(basename "$f" .json)
    jq '
      .capsule_results |= [.[] | .result_report |= (
        to_entries | map(
          if (.value | type) == "string" then
            .value |= (try tonumber catch .)
          else .
          end
        ) | from_entries
      )]
    ' "$f" > "$OUT_DIR/$agent.json"
done

echo "Normalized submissions written to $OUT_DIR/"
