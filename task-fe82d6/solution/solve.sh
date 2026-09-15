#!/bin/bash

set -e

# Install solution dependencies
pip3 install cryptography==42.0.5 requests==2.31.0 -q

# Copy solution files to /app/
cp /solution/remediate.sh /app/remediate.sh
cp /solution/byok_import.py /app/byok_import.py
chmod +x /app/remediate.sh /app/byok_import.py

# Initialize the pre-audit state
bash /app/init_state.sh
sleep 2

# Wait for OpenBao
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8200/v1/sys/health > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Run remediation
bash /app/remediate.sh
