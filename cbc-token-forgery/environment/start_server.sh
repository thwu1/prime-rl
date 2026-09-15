#!/bin/bash
# Start the crypto authentication service if not already running.
if pgrep -f "python3 /app/server.py" > /dev/null 2>&1; then
    exit 0
fi
mkdir -p /app/.state
nohup python3 /app/server.py > /app/.state/server.log 2>&1 &
for i in $(seq 1 30); do
    if curl -sf http://localhost:5000/api/health > /dev/null 2>&1; then
        exit 0
    fi
    sleep 0.5
done
echo "Server failed to start" >&2
exit 1
