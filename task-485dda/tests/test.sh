#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 requests==2.32.3 -q

# Ensure any leftover processes are stopped
pkill -f restate-server 2>/dev/null || true
pkill -f hypercorn 2>/dev/null || true
sleep 3

# Remove old restate data to start fresh
rm -rf /tmp/restate-data

# Start restate-server in background (from /tmp so data goes to /tmp/restate-data)
cd /tmp
restate-server > /tmp/restate-server.log 2>&1 &
RESTATE_PID=$!

# Wait for restate-server to be ready
for i in $(seq 1 40); do
    if curl -s http://localhost:9070/health > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! curl -s http://localhost:9070/health > /dev/null 2>&1; then
    echo "Restate server failed to start"
    echo "--- Server log ---"
    cat /tmp/restate-server.log 2>/dev/null
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

echo "Restate server is ready"

# Start the service in background
cd /app
hypercorn service:app --bind 0.0.0.0:9080 > /tmp/service.log 2>&1 &
SERVICE_PID=$!

# Wait for service to be ready
for i in $(seq 1 20); do
    if curl -s http://localhost:9080 > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

sleep 2

# Register the service deployment with Restate
restate deployments register http://localhost:9080 --yes > /tmp/register.log 2>&1

if [ $? -ne 0 ]; then
    echo "Failed to register service"
    echo "--- Register log ---"
    cat /tmp/register.log
    echo "--- Service log ---"
    cat /tmp/service.log 2>/dev/null
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

echo "Service registered"
sleep 2

# Run pytest tests
cd /tests
pytest test_state.py -v --tb=short 2>&1
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

# Cleanup
kill $SERVICE_PID 2>/dev/null || true
kill $RESTATE_PID 2>/dev/null || true

exit $TEST_EXIT
