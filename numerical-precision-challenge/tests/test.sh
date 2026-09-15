#!/bin/bash

# Pre-write failing reward so it exists even if process is killed
mkdir -p /logs/verifier
echo "0.0" > /logs/verifier/reward.txt

pip3 install pytest==8.3.4 -q 2>&1

cd /app
pytest /tests/test_state.py -v
exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
fi
exit $exit_code
