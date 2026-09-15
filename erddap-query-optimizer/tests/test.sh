#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Diagnostics: verify metadata files are in place
echo "=== Metadata files ==="
ls -la /app/metadata/*.das /app/metadata/*.dds 2>/dev/null | head -20
echo "=== Config files ==="
ls -la /app/server_registry.json /app/queries.json 2>/dev/null

# Run the agent's planner if present
if [ -f fusion_planner.py ]; then
    python3 fusion_planner.py 2>&1
elif [ -f main.py ]; then
    python3 main.py 2>&1
elif [ -f planner.py ]; then
    python3 planner.py 2>&1
fi

PLANNER_EXIT=$?
echo "=== Planner exit code: $PLANNER_EXIT ==="

# Verify output exists and is valid JSON
if [ -f /app/output/fusion_plan.json ]; then
    echo "=== Output file exists, top-level keys: ==="
    python3 -c "import json; d=json.load(open('/app/output/fusion_plan.json')); print(list(d.keys())); [print(f'  {k}: {len(v.get(\"subqueries\",[]))} subqueries') for k,v in d.items()]" 2>&1
else
    echo "=== ERROR: /app/output/fusion_plan.json not found ==="
fi

# Run tests and capture exit code
python3 -m pytest /tests/test_state.py -v --tb=short
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
