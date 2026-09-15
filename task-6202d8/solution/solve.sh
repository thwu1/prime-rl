#!/usr/bin/env bash

set -e

pip3 install requests==2.32.3 -q

cd /app

# Start DNA Center API simulator
/app/dnac/start.sh

# Wait for DNAC API to be ready
for i in $(seq 1 15); do
    if curl -s http://localhost:9443/ 2>/dev/null | grep -q ready; then
        break
    fi
    sleep 1
done

python3 /solution/network_audit.py
