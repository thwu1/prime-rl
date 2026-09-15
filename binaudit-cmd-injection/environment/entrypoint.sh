#!/bin/bash
if ! pgrep -f 'binaudit-gateway/server.py' > /dev/null 2>&1; then
    nohup python3 /opt/binaudit-gateway/server.py > /var/log/binaudit-gateway.log 2>&1 &
fi
exec "$@"
