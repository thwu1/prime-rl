#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q

# Run solver to generate results (in case agent hasn't already)
cd /app
python3 /app/run_solver.py 2>&1 || true

# Run verification tests
pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_RESULT
