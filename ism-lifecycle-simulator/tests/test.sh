#!/bin/bash

pip3 install pytest==8.3.4 -q

# Run the forensics pipeline if it exists
cd /app
if [ -f /app/run_forensics.sh ]; then
    bash /app/run_forensics.sh 2>&1
fi

# Run tests
RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?
echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
