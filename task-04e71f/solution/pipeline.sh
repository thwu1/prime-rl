#!/bin/bash
#
# SMT-COMP Model Validation Track cross-validation pipeline.
# Validates provided models and cross-checks with Z3-generated models.

BENCH_DIR="/app/benchmarks"
MODEL_DIR="/app/models"
VALIDATOR="/app/validate_model.py"
Z3SOLVE="/app/z3_solve.py"
Z3_TMP="/tmp/z3_pipeline_models"
RESULTS="/app/results.json"

mkdir -p "$Z3_TMP"

echo "{" > "$RESULTS"
first=true

for bench in $(ls "$BENCH_DIR"/case*.smt2 | sort); do
    casename=$(basename "$bench" .smt2)
    num=$(echo "$casename" | sed 's/case\([0-9]*\).*/\1/')
    suffix=$(echo "$casename" | sed 's/case[0-9]*//')
    model="$MODEL_DIR/model${num}${suffix}.smt2"

    # 1. Validate the provided model
    prov=$(python3 "$VALIDATOR" "$bench" "$model" 2>/dev/null | head -1 | tr -d '[:space:]')
    if [ "$prov" = "VALID" ]; then
        prov_json="true"
    else
        prov_json="false"
    fi

    # 2. Solve with Z3
    z3_model="$Z3_TMP/z3_${casename}.smt2"
    z3_stat=$(python3 "$Z3SOLVE" "$bench" "$z3_model" 2>/dev/null | head -1 | tr -d '[:space:]')

    # 3. Cross-validate Z3 model if sat
    z3_val_json="null"
    if [ "$z3_stat" = "sat" ] && [ -f "$z3_model" ]; then
        z3v=$(python3 "$VALIDATOR" "$bench" "$z3_model" 2>/dev/null | head -1 | tr -d '[:space:]')
        if [ "$z3v" = "VALID" ]; then
            z3_val_json="true"
        else
            z3_val_json="false"
        fi
    fi

    if [ "$first" = true ]; then
        first=false
    else
        printf ',\n' >> "$RESULTS"
    fi

    printf '  "%s": {"provided_model_valid": %s, "z3_result": "%s", "z3_model_valid": %s}' \
        "$casename" "$prov_json" "$z3_stat" "$z3_val_json" >> "$RESULTS"
done

printf '\n}\n' >> "$RESULTS"
echo "Pipeline complete. Results written to $RESULTS"
