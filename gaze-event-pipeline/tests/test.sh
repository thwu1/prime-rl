#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 numpy==2.1.3 -q

# Generate synthetic BIDS dataset
python3 /tests/generate_dataset.py /app/dataset

# Run the agent's pipeline
python3 /app/gaze_pipeline.py /app/dataset /app/output
PIPELINE_EXIT=$?

if [ $PIPELINE_EXIT -ne 0 ]; then
    echo "Pipeline exited with code $PIPELINE_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
