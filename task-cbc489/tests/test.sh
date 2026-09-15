#!/bin/bash

mkdir -p /logs/verifier

pip3 install pytest==8.3.4 -q 2>&1
if [ $? -ne 0 ]; then
    echo "Failed to install pytest" >&2
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

cd /app
python3 -m pytest /tests/test_state.py -v
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
