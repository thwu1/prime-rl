#!/bin/bash

# Solution for network control plane forensic recovery task.
# Performs multi-source evidence reconstruction using tshark, sqlite3,
# and Python to recover routing data from PCAP captures, audit logs,
# caches, and topology computation.

set -u

# Install solution dependencies
pip3 install flask==3.1.1 requests==2.32.3 -q

# Step 1: Reconstruct routing data from all evidence sources
echo "=== Step 1: Forensic route reconstruction ==="
python3 /solution/reconstruct.py

# Step 2: Fix server.ini - change maintenance port back to production port
echo "=== Step 2: Fixing server configuration ==="
sed -i 's/port = 5099/port = 5000/' /app/config/server.ini
echo "server.ini port restored to 5000"

# Step 3: Clean up stale PID files
echo "=== Step 3: Cleaning stale PID files ==="
for pid_file in /var/run/control_plane.pid /var/run/router_*.pid /var/run/health_check.pid; do
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$pid_file"
            echo "Removed stale PID file: $pid_file (PID $pid not running)"
        fi
    fi
done

# Step 4: Start the control plane server
echo "=== Step 4: Starting control plane server ==="
cd /app
nohup python3 server.py > /app/logs/server_restart.log 2>&1 &
SERVER_PID=$!
echo "Control plane server started (PID $SERVER_PID)"

# Wait for server to be ready
echo "Waiting for server to be ready..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:5000/health > /dev/null 2>&1; then
        echo "Control plane server is healthy"
        break
    fi
    if [ $i -eq 15 ]; then
        echo "ERROR: Server did not start within 15 seconds"
        cat /app/logs/server_restart.log
        exit 1
    fi
    sleep 1
done

# Step 5: Verify recovery
echo "=== Step 5: Verifying recovery ==="
ROUTE_COUNT=$(curl -sf http://localhost:5000/routes | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
echo "API serving $ROUTE_COUNT routes"

# Verify topology was fixed
LINK_COST=$(python3 -c "
import json
with open('/app/config/topology.json') as f:
    t = json.load(f)
for link in t['links']:
    if set([link['node_a'], link['node_b']]) == set(['compute-east', 'storage']):
        print(link['cost'])
")
echo "compute-east <-> storage link cost: $LINK_COST"

if [ "$ROUTE_COUNT" = "30" ] && [ "$LINK_COST" = "10" ]; then
    echo "Recovery complete: all 30 routes restored, topology fixed, API serving on port 5000"
else
    echo "WARNING: Recovery may be incomplete"
fi
