#!/usr/bin/env bash

set -u

pip3 install pytest==8.3.4 numpy==2.1.3 scipy==1.14.1 pygsp==0.6.1 -q

# Run the pipeline to generate results.json
cd /app && python3 /app/run_sgwt.py
PIPELINE_EXIT=$?

if [ $PIPELINE_EXIT -ne 0 ]; then
    echo "Pipeline failed with exit code $PIPELINE_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
