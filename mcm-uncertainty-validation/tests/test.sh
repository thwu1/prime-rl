#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q

cd /app

# Run the agent's analysis script if it exists
if [ -f run_analysis.py ]; then
    python3 run_analysis.py || echo "Warning: run_analysis.py exited with non-zero status"
fi

# Run tests
pytest /tests/test_state.py -v
exit_code=$?

# Write reward
mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
