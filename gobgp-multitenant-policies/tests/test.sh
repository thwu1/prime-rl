#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Kill any existing gobgpd so we start fresh
pkill -9 gobgpd 2>/dev/null || true
sleep 2

# Run the orchestrator (the agent's /app/orchestrator.py starts gobgpd and configures policies)
cd /app
python3 /app/orchestrator.py
orch_exit=$?
if [ $orch_exit -ne 0 ]; then
    echo "orchestrator.py failed with exit code $orch_exit"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Wait briefly for gRPC state to settle
sleep 1

# Run tests
PYTHONPATH=/app/generated:$PYTHONPATH pytest /tests/test_state.py -v
exit_code=$?

# Write reward
mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
