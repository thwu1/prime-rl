#!/bin/bash

# Detects unresolved urn:uuid: references and conditional references
# in FHIR server state resources using jq recursive descent.
# Usage: check_references.sh <output_dir>
# Exit 0 = conformant, Exit 1 = violations found

OUTPUT_DIR="${1:?Usage: $0 <output_dir>}"
STATE_DIR="$OUTPUT_DIR/server_state"

if [ ! -d "$STATE_DIR" ]; then
  echo '{"status":"error","issue_count":0,"issues":[],"error":"state directory not found"}'
  exit 1
fi

ISSUES='[]'

for f in "$STATE_DIR"/*.json; do
  [ -f "$f" ] || continue
  FNAME=$(basename "$f")

  # Detect unresolved urn:uuid: references via jq recursive descent
  URNS=$(jq '[.. | objects | select(has("reference")) | .reference | select(type == "string") | select(startswith("urn:uuid:"))]' "$f" 2>/dev/null || echo '[]')
  URN_COUNT=$(echo "$URNS" | jq 'length')

  if [ "$URN_COUNT" -gt 0 ]; then
    ISSUES=$(echo "$ISSUES" | jq --arg file "$FNAME" --argjson refs "$URNS" \
      '. + [{"file": $file, "type": "unresolved_urn_uuid", "references": $refs}]')
  fi

  # Detect unresolved conditional references (Type?search=value)
  CONDS=$(jq '[.. | objects | select(has("reference")) | .reference | select(type == "string") | select(contains("?")) | select(startswith("urn:") | not) | select(startswith("http") | not)]' "$f" 2>/dev/null || echo '[]')
  COND_COUNT=$(echo "$CONDS" | jq 'length')

  if [ "$COND_COUNT" -gt 0 ]; then
    ISSUES=$(echo "$ISSUES" | jq --arg file "$FNAME" --argjson refs "$CONDS" \
      '. + [{"file": $file, "type": "unresolved_conditional_ref", "references": $refs}]')
  fi
done

TOTAL=$(echo "$ISSUES" | jq 'length')
STATUS="pass"
EXIT_CODE=0
if [ "$TOTAL" -gt 0 ]; then
  STATUS="fail"
  EXIT_CODE=1
fi

jq -n --argjson issues "$ISSUES" --arg status "$STATUS" --argjson count "$TOTAL" \
  '{"status": $status, "issue_count": $count, "issues": $issues}'

exit $EXIT_CODE
