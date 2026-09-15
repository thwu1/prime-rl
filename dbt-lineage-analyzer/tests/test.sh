#!/bin/bash

pip3 install pytest==8.3.4 -q

# Run the agent's forensics script if present
if [ -f /app/forensics.py ]; then
    python3 /app/forensics.py
    ANALYZER_EXIT=$?
elif [ -f /app/forensics.json ]; then
    ANALYZER_EXIT=0
else
    echo "No forensics.py or forensics.json found in /app/"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

if [ $ANALYZER_EXIT -ne 0 ]; then
    echo "Forensics script failed with exit code $ANALYZER_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run verification tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
