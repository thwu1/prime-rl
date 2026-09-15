#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 numpy==2.1.3 -q

# Run agent's code if results don't exist yet
if [ ! -f /app/results.csv ]; then
    echo "results.csv not found, attempting to run agent code..."
    cd /app
    for f in natcirc.py solver.py main.py run.py analysis.py; do
        if [ -f "/app/$f" ]; then
            echo "Running /app/$f"
            python3 "/app/$f" || true
            break
        fi
    done
    # Also try running the package
    if [ ! -f /app/results.csv ]; then
        python3 -m natcirc_sim || true
    fi
fi

# Run tests
RESULT=0
python3 -m pytest /tests/test_state.py -v || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
