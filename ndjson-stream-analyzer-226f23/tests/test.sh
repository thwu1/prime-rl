#!/bin/bash

set -o pipefail

pip3 install pytest==8.3.4 -q

# Ensure simdjson is downloaded and the tool is built
cd /app
bash setup_simdjson.sh
make clean all 2>&1

# Run tests
RESULT=0
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1 || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ "$RESULT" -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit 0
