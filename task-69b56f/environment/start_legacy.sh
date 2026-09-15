#!/bin/bash
python3 /app/legacy/socks5d.pyz &
PID=$!
echo $PID > /tmp/legacy_proxy.pid
echo "Legacy proxy started on port 1080 (PID: $PID)"
echo "Stop with: kill $PID"
