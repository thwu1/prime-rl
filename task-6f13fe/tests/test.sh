#!/bin/bash

# Install test dependencies at runtime (not in Dockerfile)
pip3 install pytest==8.3.4 lz4==4.3.3 -q

# Run pytest
cd /app
pytest /tests/test_state.py -v
RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
