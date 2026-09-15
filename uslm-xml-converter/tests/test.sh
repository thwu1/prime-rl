#!/usr/bin/env bash

# Run the backfill pipeline first
python3 /app/backfill.py /app/manifest.json /app/vintages/ /app/output/repo/
TOOL_EXIT=$?

if [ $TOOL_EXIT -ne 0 ]; then
    echo "Backfill pipeline failed with exit code $TOOL_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Install test deps and run tests
pip3 install pytest==8.3.4 pyyaml==6.0.2 -q

RESULT=$(python3 -m pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

echo "$RESULT"

mkdir -p /logs/verifier

if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
