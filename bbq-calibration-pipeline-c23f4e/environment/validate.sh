#!/bin/bash
# Validate results.json schema using jq
#

set -u

RESULTS="${1:-/app/results.json}"

if [ ! -f "$RESULTS" ]; then
    echo "FAIL: results.json not found" >&2
    exit 1
fi

# Check all required top-level method keys
for method in uncalibrated histogram_binning temp_scaling bbq; do
    if ! jq -e ".\"$method\"" "$RESULTS" > /dev/null 2>&1; then
        echo "FAIL: missing method '$method'" >&2
        exit 1
    fi
done

# Check each method has required metrics
for method in $(jq -r 'keys[]' "$RESULTS"); do
    for metric in ece mce ace brier; do
        VAL=$(jq -r ".\"$method\".\"$metric\"" "$RESULTS" 2>/dev/null)
        if [ "$VAL" = "null" ] || [ -z "$VAL" ]; then
            echo "FAIL: ${method}.${metric} missing or null" >&2
            exit 1
        fi
    done
done

# Check calibrated_confidences arrays for calibration methods
for method in histogram_binning temperature_scaling bbq; do
    LEN=$(jq ".\"$method\".calibrated_confidences | length" "$RESULTS" 2>/dev/null)
    if [ -z "$LEN" ] || [ "$LEN" = "null" ] || [ "$LEN" -le 0 ] 2>/dev/null; then
        echo "FAIL: ${method}.calibrated_confidences empty or missing" >&2
        exit 1
    fi
    # Verify all values in [0, 1]
    BAD=$(jq "[.\"$method\".calibrated_confidences[] | select(. < 0 or . > 1)] | length" "$RESULTS" 2>/dev/null)
    if [ -n "$BAD" ] && [ "$BAD" -gt 0 ] 2>/dev/null; then
        echo "FAIL: ${method} has confidences outside [0,1]" >&2
        exit 1
    fi
done

# BBQ-specific checks
N_MODELS=$(jq '.bbq.num_models_selected' "$RESULTS" 2>/dev/null)
if [ "$N_MODELS" = "null" ] || [ -z "$N_MODELS" ]; then
    echo "FAIL: bbq.num_models_selected missing" >&2
    exit 1
fi

WSUM=$(jq '.bbq.model_weights | add' "$RESULTS" 2>/dev/null)
VALID=$(jq -n "$WSUM > 0.999 and $WSUM < 1.001")
if [ "$VALID" != "true" ]; then
    echo "FAIL: bbq.model_weights sum=$WSUM, expected ~1.0" >&2
    exit 1
fi

N_WEIGHTS=$(jq '.bbq.model_weights | length' "$RESULTS" 2>/dev/null)
if [ "$N_WEIGHTS" != "$N_MODELS" ]; then
    echo "FAIL: model_weights length ($N_WEIGHTS) != num_models_selected ($N_MODELS)" >&2
    exit 1
fi

# Check temperature_scaling has optimal_temperature
OT=$(jq '.temperature_scaling.optimal_temperature' "$RESULTS" 2>/dev/null)
if [ "$OT" = "null" ] || [ -z "$OT" ]; then
    echo "FAIL: temperature_scaling.optimal_temperature missing" >&2
    exit 1
fi

echo "PASS: schema validation complete"
exit 0
