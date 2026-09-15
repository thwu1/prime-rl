#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 scipy==1.14.1 pandas==2.2.3 statsmodels==0.14.4 -q

cd /app && python3 count_pipeline.py
PIPELINE_EXIT=$?

if [ $PIPELINE_EXIT -ne 0 ]; then
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
