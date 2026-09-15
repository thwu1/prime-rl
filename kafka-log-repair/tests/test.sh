#!/bin/bash

# Install pytest
python3 -m pip install pytest==8.3.4 -q 2>&1 || pip3 install pytest==8.3.4 -q 2>&1 || true

# Kill any existing broker on port 9092
pkill -f "python3 /app/broker.py" 2>/dev/null || true
sleep 1

# Start broker if it exists
BROKER_PID=""
if [ -f /app/broker.py ]; then
    python3 /app/broker.py > /tmp/broker.log 2>&1 &
    BROKER_PID=$!
    # Wait for broker to be ready (up to 20 seconds)
    for i in $(seq 1 40); do
        python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost',9092)); s.close()" 2>/dev/null && break
        sleep 0.5
    done
fi

RESULT=$(python3 -m pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

# Kill broker
if [ -n "$BROKER_PID" ]; then
    kill $BROKER_PID 2>/dev/null
    wait $BROKER_PID 2>/dev/null
fi

echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
