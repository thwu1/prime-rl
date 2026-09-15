#!/bin/bash

# Install solution dependencies
pip3 install restate-sdk==0.18.1 hypercorn==0.18.0 -q

# Kill any existing processes
pkill -f restate-server 2>/dev/null || true
pkill -f hypercorn 2>/dev/null || true
sleep 3
rm -rf /tmp/restate-data

# Copy the fixed service into place
cp /solution/fixed_service.py /app/service.py

# Start Restate server (from /tmp so data goes to /tmp/restate-data)
cd /tmp
restate-server > /tmp/restate-server.log 2>&1 &
RESTATE_PID=$!

# Wait for Restate server to be ready
for i in $(seq 1 40); do
    if curl -s http://localhost:9070/health > /dev/null 2>&1; then
        echo "Restate server is ready"
        break
    fi
    sleep 1
done

if ! curl -s http://localhost:9070/health > /dev/null 2>&1; then
    echo "ERROR: Restate server failed to start"
    cat /tmp/restate-server.log
    exit 1
fi

# Start the Python service
cd /app
hypercorn service:app --bind 0.0.0.0:9080 > /tmp/service.log 2>&1 &
SERVICE_PID=$!

# Wait for service to be ready
for i in $(seq 1 20); do
    if curl -s http://localhost:9080 > /dev/null 2>&1; then
        echo "Service is ready"
        break
    fi
    sleep 1
done

sleep 2

# Register the service with Restate
restate deployments register http://localhost:9080 --yes
echo "Service registered successfully"
