#!/bin/bash

pip3 install pytest==8.3.4 -q

# Kill any leftover server
pkill -f "python3 /app/server.py" 2>/dev/null || true
sleep 1

# Start server
python3 /app/server.py &
SERVER_PID=$!
sleep 2

# Run tests
python3 -m pytest /tests/test_state.py -v
RESULT=$?

# Cleanup
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
