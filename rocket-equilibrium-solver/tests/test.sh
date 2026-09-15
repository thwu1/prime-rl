#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 scipy==1.14.1 -q

# Run the solver if results don't exist yet
cd /app
if [ -f /app/rocket_eq.py ]; then
    python3 /app/rocket_eq.py 2>&1
fi

# Run tests and capture exit code
pytest /tests/test_state.py -v
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_RC
