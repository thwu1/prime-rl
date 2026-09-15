#!/bin/bash

# Start redis-server with the provided config
redis-server /app/valkey.conf --daemonize yes 2>/dev/null || true

# Wait for server to be ready
for i in $(seq 1 30); do
    redis-cli -p 6379 PING > /dev/null 2>&1 && break
    sleep 0.5
done

# Run the audit
python3 /solution/audit.py

# Shutdown server
redis-cli -p 6379 SHUTDOWN NOSAVE 2>/dev/null || true
