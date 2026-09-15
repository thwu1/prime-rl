#!/bin/bash

# Ensure input data exists
if [ ! -f /app/data/survey.las ]; then
    python3 /app/generate_input.py
fi

# Run the solver's pipeline if process.sh exists
if [ -f /app/process.sh ]; then
    chmod +x /app/process.sh
    cd /app && bash /app/process.sh || true
fi

# Run tests
RESULT=0
python3 -m pytest /tests/test_state.py -v --tb=short || RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
