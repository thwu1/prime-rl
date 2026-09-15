#!/bin/bash
# Pipeline orchestration script
# Reads scenario configs and runs solver on each instance

CONFIG="/app/pipeline/config.ini"

get_config() {
    grep "^$1" "$CONFIG" | cut -d= -f2 | tr -d ' '
}

SCENARIO_DIR=$(get_config scenario_dir)
INSTANCE_DIR=$(get_config instance_dir)
OUTPUT_DIR=$(get_config output_dir)
SOLVER=$(get_config solver_script)
TIME_LIMIT=$(get_config time_limit_sec)

mkdir -p "$OUTPUT_DIR"

PASSED=0
TOTAL=0

for scenario_file in "$SCENARIO_DIR"/*.json; do
    TOTAL=$((TOTAL + 1))
    scenario_name=$(python3 -c "import json; print(json.load(open('$scenario_file'))['name'])")
    instance=$(python3 -c "import json; print(json.load(open('$scenario_file'))['instance_file'])")
    threshold=$(python3 -c "import json; print(json.load(open('$scenario_file'))['max_objective'])")

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running solver on $instance for $scenario_name..."

    timeout "$TIME_LIMIT" python3 "$SOLVER" "$INSTANCE_DIR/$instance" > "$OUTPUT_DIR/${scenario_name}.sol" 2>/dev/null
    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        if [ $EXIT_CODE -eq 124 ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] TIMEOUT: Solver exceeded ${TIME_LIMIT}s limit for $scenario_name"
        else
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Solver failed with exit code $EXIT_CODE"
        fi
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Solver completed for $scenario_name. Validating..."
        python3 /app/tools/validate.py "$INSTANCE_DIR/$instance" "$OUTPUT_DIR/${scenario_name}.sol" "$scenario_file"
        if [ $? -eq 0 ]; then
            PASSED=$((PASSED + 1))
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] $scenario_name: PASSED"
        else
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] $scenario_name: FAILED"
        fi
    fi
    echo ""
done

echo "=== Summary: $PASSED/$TOTAL scenarios passed ==="
