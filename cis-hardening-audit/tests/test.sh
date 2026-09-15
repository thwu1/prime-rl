#!/bin/bash

# Install test dependencies at runtime (NOT in the Dockerfile)
pip3 install pytest==8.3.4 -q

# Run pytest — capture exit code without set -e
cd /app
EXITCODE=0
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1 || EXITCODE=$?

# Write reward
mkdir -p /logs/verifier
if [ "$EXITCODE" -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXITCODE
