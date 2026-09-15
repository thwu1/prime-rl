#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Kill any existing mock services and start fresh
pkill -f svc_binary.py 2>/dev/null || true
pkill -f svc_http.py 2>/dev/null || true
sleep 1

# Start mock services for integration tests
/app/start_services.sh 2>/dev/null || true
sleep 3

# Run tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Kill mock services
pkill -f svc_binary.py 2>/dev/null || true
pkill -f svc_http.py 2>/dev/null || true

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
