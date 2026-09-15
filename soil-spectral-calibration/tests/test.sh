#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 scipy==1.14.1 scikit-learn==1.5.2 -q

# Generate data if not present
python3 /app/generate_data.py

# Run the solver's pipeline
python3 /app/calibrate.py
PIPELINE_EXIT=$?

if [ $PIPELINE_EXIT -ne 0 ]; then
    echo "calibrate.py failed with exit code $PIPELINE_EXIT"
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
