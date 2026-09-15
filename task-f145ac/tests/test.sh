#!/bin/bash

# Start the server in the background
python3 /app/server.py &
SERVER_PID=$!

# Wait for server to be ready (up to 5 seconds)
for i in $(seq 1 10); do
    if python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',9999)); s.close()" 2>/dev/null; then
        break
    fi
    sleep 0.5
done

# Verify server is running
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "Server failed to start"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Cleanup
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
