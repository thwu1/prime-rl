#!/usr/bin/env bash

# Ensure BIND is running (the agent should have configured and started it)
if ! pgrep -x named > /dev/null 2>&1; then
    mkdir -p /run/named
    named -c /etc/bind/named.conf 2>/dev/null || true
    sleep 3
fi

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run tests
cd /tests
RESULT=0
python3 -m pytest test_state.py -v --tb=short || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
