#!/bin/bash

pip3 install pytest==8.3.4 -q

# Re-run the analysis pipeline to verify reproducibility
if [ ! -f /app/run_analysis.sh ]; then
    echo "FAIL: /app/run_analysis.sh not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

rm -rf /app/output
mkdir -p /app/output
bash /app/run_analysis.sh
RUN_EXIT=$?
if [ $RUN_EXIT -ne 0 ]; then
    echo "run_analysis.sh exited with code $RUN_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

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
