#!/bin/bash
# Start mock services for the metric collection environment.
# Binary protocol services on ports 9001, 9002, 9004.
# Port 9003 runs the health-check HTTP endpoint.

python3 /app/services/svc_binary.py 9001 svc-alpha >/dev/null 2>&1 &
python3 /app/services/svc_binary.py 9002 svc-beta  >/dev/null 2>&1 &
python3 /app/services/svc_binary.py 9004 svc-delta >/dev/null 2>&1 &
python3 /app/services/svc_http.py 9003             >/dev/null 2>&1 &

sleep 1
echo "Services started on ports 9001, 9002, 9003, 9004"
