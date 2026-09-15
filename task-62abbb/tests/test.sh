#!/bin/bash

pip3 install pytest==8.3.4 pyyaml==6.0.2 -q

cd /app

# Run the selector engine (produces results.json and lineage.dot)
python3 /app/selector_engine.py

# Generate SVG from DOT if lineage.dot exists
if [ -f /app/lineage.dot ]; then
    dot -Tsvg /app/lineage.dot -o /app/lineage.svg 2>/dev/null || true
fi

# Run jq analysis if the jq script exists
if [ -f /app/analyze_manifest.jq ]; then
    jq -f /app/analyze_manifest.jq /app/manifest.json > /app/manifest_analysis.json 2>/dev/null || true
fi

PYTEST_EXIT=0
pytest /tests/test_state.py -v || PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
