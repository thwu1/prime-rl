#!/bin/bash

# Produces a structured JSON comparison of conformance indicators
# across all three processor outputs.
# Usage: diff_processors.sh (no arguments)

get_metrics() {
  local OUTPUT_DIR="$1"
  local STATE_DIR="$OUTPUT_DIR/server_state"
  local BUNDLE="$OUTPUT_DIR/response_bundle.json"

  RESOURCE_COUNT=$(ls "$STATE_DIR"/*.json 2>/dev/null | wc -l)

  URN_COUNT=0
  COND_REF_COUNT=0
  for f in "$STATE_DIR"/*.json; do
    [ -f "$f" ] || continue
    U=$(jq '[.. | objects | select(has("reference")) | .reference | select(type == "string") | select(startswith("urn:uuid:"))] | length' "$f" 2>/dev/null || echo 0)
    URN_COUNT=$((URN_COUNT + U))
    C=$(jq '[.. | objects | select(has("reference")) | .reference | select(type == "string") | select(contains("?")) | select(startswith("urn:") | not) | select(startswith("http") | not)] | length' "$f" 2>/dev/null || echo 0)
    COND_REF_COUNT=$((COND_REF_COUNT + C))
  done

  DELETE_STATUS=$(jq -r '.entry[0].response.status // "missing"' "$BUNDLE" 2>/dev/null || echo "missing")

  ALLERGY_COUNT=0
  for f in "$STATE_DIR"/AllergyIntolerance_*.json; do
    [ -f "$f" ] && ALLERGY_COUNT=$((ALLERGY_COUNT + 1))
  done

  # Check PUT versioning for Patient/pat-002
  PUT_VERSION="unknown"
  PAT002="$STATE_DIR/Patient_pat-002.json"
  if [ -f "$PAT002" ]; then
    PUT_VERSION=$(jq -r '.meta.versionId // "missing"' "$PAT002")
  fi

  HAS_LAST_UPDATED="unknown"
  if [ -f "$PAT002" ]; then
    HAS_LAST_UPDATED=$(jq 'if .meta then (.meta | has("lastUpdated")) else false end' "$PAT002")
  fi

  jq -n \
    --argjson resources "$RESOURCE_COUNT" \
    --argjson unresolved_urn_uuids "$URN_COUNT" \
    --argjson unresolved_conditional_refs "$COND_REF_COUNT" \
    --arg delete_status "$DELETE_STATUS" \
    --argjson allergy_count "$ALLERGY_COUNT" \
    --arg put_version "$PUT_VERSION" \
    --arg has_last_updated "$HAS_LAST_UPDATED" \
    '{
      "resource_count": $resources,
      "unresolved_urn_uuids": $unresolved_urn_uuids,
      "unresolved_conditional_refs": $unresolved_conditional_refs,
      "delete_response_status": $delete_status,
      "allergy_intolerance_count": $allergy_count,
      "put_version_id": $put_version,
      "put_has_last_updated": $has_last_updated
    }'
}

METRICS_A=$(get_metrics "/app/output_a")
METRICS_B=$(get_metrics "/app/output_b")
METRICS_C=$(get_metrics "/app/output_c")

jq -n \
  --argjson a "$METRICS_A" \
  --argjson b "$METRICS_B" \
  --argjson c "$METRICS_C" \
  '{"processor_a": $a, "processor_b": $b, "processor_c": $c}'
