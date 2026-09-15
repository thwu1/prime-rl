#!/bin/bash

# Verifies meta.versionId increment and meta.lastUpdated presence
# for PUT-updated resources by comparing output against initial state.
# Usage: check_versioning.sh <output_dir> <initial_state_dir>
# Exit 0 = conformant, Exit 1 = violations found

OUTPUT_DIR="${1:?Usage: $0 <output_dir> <initial_state_dir>}"
INITIAL_DIR="${2:?Usage: $0 <output_dir> <initial_state_dir>}"
INPUT_BUNDLE="/app/data/transaction_bundle.json"

OUTPUT_STATE="$OUTPUT_DIR/server_state"

ISSUES='[]'

NUM_ENTRIES=$(jq '.entry | length' "$INPUT_BUNDLE")

for i in $(seq 0 $(($NUM_ENTRIES - 1))); do
  METHOD=$(jq -r ".entry[$i].request.method // \"\"" "$INPUT_BUNDLE" | tr '[:lower:]' '[:upper:]')
  URL=$(jq -r ".entry[$i].request.url // \"\"" "$INPUT_BUNDLE")

  if [ "$METHOD" = "PUT" ] && [ -n "$URL" ]; then
    RTYPE=$(echo "$URL" | cut -d'/' -f1)
    RID=$(echo "$URL" | cut -d'/' -f2)

    INITIAL_FILE="$INITIAL_DIR/${RTYPE}_${RID}.json"
    OUTPUT_FILE="$OUTPUT_STATE/${RTYPE}_${RID}.json"

    if [ -f "$INITIAL_FILE" ] && [ -f "$OUTPUT_FILE" ]; then
      OLD_VERSION=$(jq -r '.meta.versionId // "0"' "$INITIAL_FILE")
      NEW_VERSION=$(jq -r '.meta.versionId // "0"' "$OUTPUT_FILE")
      HAS_LAST_UPDATED=$(jq 'if .meta then (.meta | has("lastUpdated")) else false end' "$OUTPUT_FILE")

      if [ "$NEW_VERSION" -le "$OLD_VERSION" ] 2>/dev/null; then
        ISSUES=$(echo "$ISSUES" | jq \
          --arg url "$URL" \
          --arg old "$OLD_VERSION" \
          --arg new "$NEW_VERSION" \
          '. + [{"resource": $url, "type": "version_not_incremented", "old_version": $old, "new_version": $new}]')
      fi

      if [ "$HAS_LAST_UPDATED" = "false" ]; then
        ISSUES=$(echo "$ISSUES" | jq --arg url "$URL" \
          '. + [{"resource": $url, "type": "missing_lastUpdated"}]')
      fi
    fi
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
