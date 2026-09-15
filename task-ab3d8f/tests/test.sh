#!/usr/bin/env bash


pip3 install pytest==8.3.4 -q

# Verify server entry point exists
if [ ! -f /app/server.py ]; then
    echo "Error: /app/server.py not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Start the server
cd /app
python3 /app/server.py &
SERVER_PID=$!

# Wait for server to be ready (up to 20 seconds)
SERVER_READY=0
for i in $(seq 1 40); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "Server process died unexpectedly"
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
        exit 1
    fi
    if python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost', 9000)); s.close()" 2>/dev/null; then
        SERVER_READY=1
        break
    fi
    sleep 0.5
done

if [ "$SERVER_READY" -eq 0 ]; then
    echo "Server failed to start listening on port 9000 within 20 seconds"
    kill "$SERVER_PID" 2>/dev/null
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

echo "Server is ready on port 9000 (PID $SERVER_PID)"

# Run tests
pytest /tests/test_state.py -v --tb=short
TEST_EXIT=$?

# Cleanup
kill "$SERVER_PID" 2>/dev/null
wait "$SERVER_PID" 2>/dev/null

# Write reward
mkdir -p /logs/verifier
if [ "$TEST_EXIT" -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
