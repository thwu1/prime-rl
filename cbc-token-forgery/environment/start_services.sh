#!/bin/bash
# Start crypto services if not already running.
if pgrep -f "/usr/local/bin/services" > /dev/null 2>&1; then
    exit 0
fi
mkdir -p /var/run/svc
nohup /usr/local/bin/services > /var/run/svc/services.log 2>&1 &
for i in $(seq 1 30); do
    if curl -sf http://localhost:5001/api/health > /dev/null 2>&1 && \
       curl -sf http://localhost:5002/api/health > /dev/null 2>&1 && \
       curl -ksf https://localhost:5003/api/health > /dev/null 2>&1; then
        exit 0
    fi
    sleep 0.5
done
echo "Services failed to start" >&2
exit 1
