#!/bin/bash

set -e

# Install solution dependencies
pip3 install pyyaml==6.0.2 flask==3.1.0 requests==2.32.3 -q

# Run the comprehensive fix script
python3 /solution/fix_system.py

echo "=== Solution applied. Verifying system health... ==="

# Start service-control on port 15099 and verify
INSTANCE_ID=verify REGION=region1 PORT=15099 python3 /app/service_control/server.py &
SC_PID=$!
sleep 3

HEALTH=$(python3 -c "
import requests
try:
    r = requests.get('http://localhost:15099/health', timeout=5)
    print(r.json())
except Exception as e:
    print(f'FAIL: {e}')
")
echo "Health check: $HEALTH"

kill $SC_PID 2>/dev/null || true
wait $SC_PID 2>/dev/null || true

echo "=== Solution complete ==="
