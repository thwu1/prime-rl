#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

cd /app

RESULT=$(python3 -m pytest /tests/test_state.py -v 2>&1) || true
echo "$RESULT"

if echo "$RESULT" | grep -q "failed"; then
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    echo "TESTS FAILED"
    exit 1
elif echo "$RESULT" | grep -q "passed"; then
    mkdir -p /logs/verifier
    echo "1.0" > /logs/verifier/reward.txt
    echo "ALL TESTS PASSED"
    exit 0
else
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    echo "TESTS DID NOT RUN PROPERLY"
    exit 1
fi
