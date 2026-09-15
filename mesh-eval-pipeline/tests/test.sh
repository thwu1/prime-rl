#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run the evaluation pipeline using the current evaluate.py
python3 /app/evaluate.py \
    --pairs /app/models/pairs.json \
    --samples 10000 \
    --voxel-res 32 \
    --seed 42 \
    --output /app/results.json 2>&1 || true

# Run pytest and capture exit code
pytest /tests/test_state.py -v
RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
