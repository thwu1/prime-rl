#!/bin/bash

# Batch fuzzing driver.
# Usage: batch.sh START_SEED END_SEED
# Writes /app/pipeline/report.json

START="${1:?Usage: batch.sh START END}"
END="${2:?Usage: batch.sh START END}"

FUZZ="/app/pipeline/fuzz.sh"
REPORT="/app/pipeline/report.json"

PASS=0
MISMATCH=0
CRASH=0
TIMEOUT_COUNT=0
COMPILE_ERROR=0
UB=0

RESULTS="[]"

for SEED in $(seq "$START" "$END"); do
    RESULT=$("$FUZZ" --seed "$SEED" 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$RESULT" ]; then
        # fuzz.sh failed entirely; record as compile_error
        RESULT=$(jq -n --argjson seed "$SEED" '{status:"compile_error",seed:$seed,outputs:{},details:"fuzz.sh failed"}')
    fi

    STATUS=$(echo "$RESULT" | jq -r '.status' 2>/dev/null)

    case "$STATUS" in
        pass)          PASS=$((PASS + 1)) ;;
        mismatch)      MISMATCH=$((MISMATCH + 1)) ;;
        crash)         CRASH=$((CRASH + 1)) ;;
        timeout)       TIMEOUT_COUNT=$((TIMEOUT_COUNT + 1)) ;;
        compile_error) COMPILE_ERROR=$((COMPILE_ERROR + 1)) ;;
        ub)            UB=$((UB + 1)) ;;
        *)             COMPILE_ERROR=$((COMPILE_ERROR + 1)) ;;
    esac

    RESULTS=$(echo "$RESULTS" | jq --argjson r "$RESULT" '. + [$r]')
done

TOTAL=$((PASS + MISMATCH + CRASH + TIMEOUT_COUNT + COMPILE_ERROR + UB))

jq -n \
    --argjson total "$TOTAL" \
    --argjson pass "$PASS" \
    --argjson mismatch "$MISMATCH" \
    --argjson crash "$CRASH" \
    --argjson timeout "$TIMEOUT_COUNT" \
    --argjson compile_error "$COMPILE_ERROR" \
    --argjson ub "$UB" \
    --argjson results "$RESULTS" \
    '{total:$total, pass:$pass, mismatch:$mismatch, crash:$crash,
      timeout:$timeout, compile_error:$compile_error, ub:$ub,
      results:$results}' \
    > "$REPORT"

echo "Report written to $REPORT"
echo "Summary: total=$TOTAL pass=$PASS mismatch=$MISMATCH crash=$CRASH timeout=$TIMEOUT_COUNT compile_error=$COMPILE_ERROR ub=$UB"
