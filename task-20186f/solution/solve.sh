#!/bin/bash

# Deploy the simulator implementation
cp /solution/simulator.py /app/simulator.py

# Verify protocol invariants with TLC model checker
cd /app/spec
java -cp /app/tools/tla2tools.jar tlc2.TLC kip966.tla -config kip966.cfg -workers 1 2>&1 | tail -5
TLC_EXIT=$?
echo "TLC exit code: $TLC_EXIT"

# Verify simulator against all scenarios
cd /app
PASS=0
FAIL=0
for scenario in /app/scenarios/*.json; do
    NAME=$(basename "$scenario")
    OUTPUT=$(python3 run_scenario.py "$scenario" 2>&1)
    if [ $? -eq 0 ]; then
        echo "PASS: $NAME"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $NAME"
        echo "$OUTPUT"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "Results: $PASS passed, $FAIL failed out of $((PASS + FAIL)) scenarios"
