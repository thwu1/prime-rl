#!/bin/bash

pip3 install pytest==8.3.4 pyyaml==6.0.2 -q

# Run the transform engine
python3 /app/transform_engine.py
ENGINE_EXIT=$?

if [ $ENGINE_EXIT -ne 0 ]; then
    echo "Transform engine failed with exit code $ENGINE_EXIT"
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
