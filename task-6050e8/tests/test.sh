#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 pytest-asyncio==0.24.0 -q

# Check that run.sh exists
if [ ! -f /app/run.sh ]; then
    echo "Error: /app/run.sh not found. The server must be startable via bash /app/run.sh."
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Start the server in the background
cd /app
bash /app/run.sh &
SERVER_PID=$!

# Wait for server to be ready (up to 10 seconds)
READY=0
for i in $(seq 1 100); do
    if python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', 9000)); s.close()" 2>/dev/null; then
        READY=1
        break
    fi
    sleep 0.1
done

if [ "$READY" -ne 1 ]; then
    echo "Error: Server did not start listening on port 9000 within 10 seconds."
    kill $SERVER_PID 2>/dev/null
    wait $SERVER_PID 2>/dev/null
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
python3 -m pytest /tests/test_state.py -v -o asyncio_mode=auto
EXIT_CODE=$?

# Cleanup
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
