#!/bin/bash

pip3 install pytest==8.3.4 pytest-timeout==2.3.1 -q 2>/dev/null

# Kill any stale processes on the test ports
for port in 9877 9878; do
    pid=$(lsof -ti tcp:$port 2>/dev/null)
    if [ -n "$pid" ]; then
        kill $pid 2>/dev/null
        sleep 1
    fi
done

wait_for_port() {
    local port=$1
    local max_tries=15
    local i=0
    while [ $i -lt $max_tries ]; do
        if python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',$port)); s.close()" 2>/dev/null; then
            return 0
        fi
        sleep 1
        i=$((i + 1))
    done
    return 1
}

# Start original server on port 9877
python3 /app/voicelink/server.py > /tmp/server_orig.log 2>&1 &
ORIG_PID=$!
if ! wait_for_port 9877; then
    echo "ERROR: Original server failed to start on port 9877"
    cat /tmp/server_orig.log
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Start hardened server on port 9878 if it exists
HARD_PID=""
if [ -f /app/voicelink/server_hardened.py ]; then
    VLSP_PORT=9878 python3 /app/voicelink/server_hardened.py > /tmp/server_hard.log 2>&1 &
    HARD_PID=$!
    if ! wait_for_port 9878; then
        echo "WARNING: Hardened server failed to start on port 9878"
        cat /tmp/server_hard.log
    fi
fi

cd /app
python3 -m pytest /tests/test_state.py -v --tb=short --timeout=60 2>&1
RESULT=$?

# Clean up servers
kill "$ORIG_PID" 2>/dev/null
wait "$ORIG_PID" 2>/dev/null || true
if [ -n "$HARD_PID" ]; then
    kill "$HARD_PID" 2>/dev/null
    wait "$HARD_PID" 2>/dev/null || true
fi

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
