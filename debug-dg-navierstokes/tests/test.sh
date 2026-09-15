#!/bin/bash


# Install test dependencies (pinned versions)
pip3 install pytest==8.3.4 -q

# Remove stale results to ensure fresh computation
rm -f /app/results.json

# Check that the solver exists
if [ ! -f /app/solver.py ]; then
    echo "ERROR: /app/solver.py not found — solver was not implemented"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the solver to generate results
cd /app
python3 /app/solver.py
solver_exit=$?

if [ $solver_exit -ne 0 ]; then
    echo "ERROR: solver.py exited with code $solver_exit"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run verification tests
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
