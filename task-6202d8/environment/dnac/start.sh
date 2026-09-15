#!/usr/bin/env bash
# Start DNA Center API simulator in the background
if pgrep -f "dnac_api.py" > /dev/null 2>&1; then
    echo "DNA Center API already running"
else
    nohup python3 /app/dnac/dnac_api.py 9443 > /var/log/dnac_api.log 2>&1 &
    echo "DNA Center API simulator started on port 9443 (PID: $!)"
fi
