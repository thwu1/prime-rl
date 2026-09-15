#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q

cd /app

# Verify the full make pipeline works end-to-end
make clean 2>/dev/null || true
make all
MAKE_EXIT=$?

if [ $MAKE_EXIT -ne 0 ]; then
    echo "make all failed with exit code $MAKE_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest verification of outputs
RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?
echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
