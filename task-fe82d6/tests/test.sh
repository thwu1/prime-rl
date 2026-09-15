#!/bin/bash

# Install test dependencies
pip3 install pytest==8.2.0 requests==2.31.0 -q

# Kill any existing bao process for a clean start
pkill -f "bao server" 2>/dev/null || true
sleep 3

# Initialize the pre-audit state
if [ ! -f /app/init_state.sh ]; then
    echo "ERROR: /app/init_state.sh not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

bash /app/init_state.sh || true
sleep 2

# Verify OpenBao is ready after init
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8200/v1/sys/health > /dev/null 2>&1; then
        echo "OpenBao ready after init"
        break
    fi
    sleep 1
done

# Run the agent's remediation script
if [ ! -f /app/remediate.sh ]; then
    echo "ERROR: /app/remediate.sh not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

cd /app
bash /app/remediate.sh || true
sleep 2

# Verify OpenBao is still running after remediation
for i in $(seq 1 15); do
    if curl -s http://127.0.0.1:8200/v1/sys/health > /dev/null 2>&1; then
        echo "OpenBao running after remediation"
        break
    fi
    sleep 1
done

# Run pytest
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
