#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q

# Run optimization if result.json does not exist yet but optimize.py does
if [ ! -f /app/result.json ] && [ -f /app/optimize.py ]; then
    cd /app && python3 optimize.py
fi

pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_RESULT
