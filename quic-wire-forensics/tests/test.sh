#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Try to run the analyzer if report.json doesn't exist
if [ ! -f /app/report.json ]; then
    for script in /app/quic_analyzer.py /app/analyzer.py /app/solve.py /app/main.py; do
        if [ -f "$script" ]; then
            cd /app && python3 "$script" 2>/dev/null
            break
        fi
    done
fi

# Run tests
cd /app
python3 -m pytest /tests/test_state.py -v
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
