#!/bin/bash

pip3 install pytest==8.3.4 -q

# Run the full pipeline
cd /app
bash /app/pipeline.sh
PIPELINE_RESULT=$?

if [ $PIPELINE_RESULT -ne 0 ]; then
    echo "Pipeline failed with exit code $PIPELINE_RESULT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run verification tests
pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
