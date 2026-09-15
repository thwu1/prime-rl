#!/bin/bash

# Validates response Bundle entry status codes against FHIR R5 requirements.
# Usage: check_status_codes.sh <output_dir>
# Exit 0 = conformant, Exit 1 = violations found

OUTPUT_DIR="${1:?Usage: $0 <output_dir>}"
BUNDLE="$OUTPUT_DIR/response_bundle.json"
INPUT_BUNDLE="/app/data/transaction_bundle.json"

if [ ! -f "$BUNDLE" ]; then
  echo '{"status":"error","issue_count":0,"issues":[],"error":"response bundle not found"}'
  exit 1
fi

ISSUES='[]'

NUM_ENTRIES=$(jq '.entry | length' "$INPUT_BUNDLE")

for i in $(seq 0 $(($NUM_ENTRIES - 1))); do
  METHOD=$(jq -r ".entry[$i].request.method // \"\"" "$INPUT_BUNDLE" | tr '[:lower:]' '[:upper:]')
  STATUS=$(jq -r ".entry[$i].response.status // \"\"" "$BUNDLE")
  HAS_IF_NONE_EXIST=$(jq -r ".entry[$i].request.ifNoneExist // \"\"" "$INPUT_BUNDLE")

  EXPECTED=""
  case "$METHOD" in
    DELETE) EXPECTED="204" ;;
    POST)
      if [ -n "$HAS_IF_NONE_EXIST" ]; then
        EXPECTED="200|201"
      else
        EXPECTED="201"
      fi
      ;;
    PUT) EXPECTED="200|201" ;;
  esac

  if [ -n "$EXPECTED" ]; then
    MATCH=false
    IFS='|' read -ra CODES <<< "$EXPECTED"
    for code in "${CODES[@]}"; do
      if echo "$STATUS" | grep -qw "$code"; then
        MATCH=true
        break
      fi
    done

    if [ "$MATCH" = false ]; then
      ISSUES=$(echo "$ISSUES" | jq \
        --argjson idx "$i" \
        --arg method "$METHOD" \
        --arg status "$STATUS" \
        --arg expected "$EXPECTED" \
        '. + [{"entry_index": $idx, "method": $method, "actual_status": $status, "expected_pattern": $expected}]')
    fi
  fi
done

TOTAL=$(echo "$ISSUES" | jq 'length')
STATUS_RESULT="pass"
EXIT_CODE=0
if [ "$TOTAL" -gt 0 ]; then
  STATUS_RESULT="fail"
  EXIT_CODE=1
fi

jq -n --argjson issues "$ISSUES" --arg status "$STATUS_RESULT" --argjson count "$TOTAL" \
  '{"status": $status, "issue_count": $count, "issues": $issues}'

exit $EXIT_CODE
