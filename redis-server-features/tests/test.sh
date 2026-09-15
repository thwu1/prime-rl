#!/bin/bash

pip3 install pytest==8.3.4 -q

# Kill any lingering server
pkill -f '/app/server' 2>/dev/null || true
sleep 0.3

# Run pytest (the fixture handles build + server lifecycle)
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Clean up
pkill -f '/app/server' 2>/dev/null || true

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
