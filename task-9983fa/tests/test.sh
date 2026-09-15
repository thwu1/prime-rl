#!/bin/bash

pip3 install pytest==8.3.4 pyyaml==6.0.2 -q

# Stop any running CrowdSec
pkill -9 crowdsec 2>/dev/null || true
sleep 2

# Clean state: wipe database but keep hub and config
rm -rf /var/lib/crowdsec/data/
mkdir -p /var/lib/crowdsec/data/
cscli machines add -a --force 2>/dev/null || true

# Prepare log replay: CrowdSec tails from end-of-file by default,
# so we empty the file first and append data after CrowdSec starts.
if [ -f /app/logs/gateway.log ]; then
    cp /app/logs/gateway.log /tmp/gateway_data.log
    : > /app/logs/gateway.log
fi

# Start CrowdSec in foreground mode (background via shell)
crowdsec > /tmp/crowdsec.log 2>&1 &
sleep 10

# Replay log data so CrowdSec sees it as new content
if [ -f /tmp/gateway_data.log ]; then
    cat /tmp/gateway_data.log >> /app/logs/gateway.log
fi

# Wait for scenario processing
sleep 30

# Run tests
pytest /tests/test_state.py -v
EXIT_CODE=$?

# Cleanup
pkill crowdsec 2>/dev/null || true

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
