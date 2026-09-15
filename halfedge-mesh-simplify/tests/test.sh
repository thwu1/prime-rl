#!/usr/bin/env bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q

RESULT=$(python3 -m pytest /tests/test_state.py -v --tb=short 2>&1) || true
echo "$RESULT"

mkdir -p /logs/verifier

if echo "$RESULT" | grep -q "failed"; then
    echo "0.0" > /logs/verifier/reward.txt
elif echo "$RESULT" | grep -q "passed"; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
