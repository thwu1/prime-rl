#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

cd /app

# Run agent's tshark extraction script if present
if [ -f /app/tshark_extract.sh ]; then
    bash /app/tshark_extract.sh 2>&1
fi

# Run the shaper if both trace and shaper exist
if [ -f /app/trace.csv ] && [ -f /app/shaper.py ]; then
    python3 /app/run_shaper.py 2>&1
fi

# Run tests
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
