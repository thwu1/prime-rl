#!/bin/bash

python3 -m pip install pytest==8.3.4 numpy==2.1.3 scipy==1.14.1 -q

cd /app
python3 /app/compute_properties.py 2>&1 || true

python3 -m pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RESULT
