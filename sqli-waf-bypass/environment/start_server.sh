#!/bin/bash
# Start Redis and Flask for the MegaCorp Employee Directory

# If both services are already healthy, nothing to do
if pgrep -x redis-server > /dev/null 2>&1 && curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    exit 0
fi

# Clean up any partial state
pkill -x redis-server 2>/dev/null || true
pkill -f "python3 /app/app.py" 2>/dev/null || true
sleep 1

# Generate a random authentication token for Redis
REDIS_AUTH_TOKEN=$(python3 -c "import os; print(os.urandom(12).hex())")

# Start Redis with authentication enabled
redis-server --daemonize yes --requirepass "$REDIS_AUTH_TOKEN" --port 6379 --loglevel warning
sleep 1

# Start the Flask application (reads REDIS_AUTH_TOKEN from environment)
REDIS_AUTH_TOKEN="$REDIS_AUTH_TOKEN" nohup python3 /app/app.py > /app/app.log 2>&1 &

# Wait for Flask health endpoint
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        echo "[+] All services started"
        exit 0
    fi
    sleep 1
done

echo "[-] Startup failed" >&2
cat /app/app.log >&2 2>/dev/null
exit 1
