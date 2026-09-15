#!/bin/bash

# Restore task data from durable backup if /app/ was mounted as a volume
if [ ! -f /app/config/instance.json ]; then
    mkdir -p /app/config /app/data /app/spec
    cp -r /opt/task-data/config/. /app/config/
    cp -r /opt/task-data/data/. /app/data/
    cp -r /opt/task-data/spec/. /app/spec/
fi

# Server uses only stdlib + cryptography (already in Dockerfile), no pip needed.
cp /solution/server.py /app/server.py
cp /solution/start.sh /app/start.sh
chmod +x /app/start.sh
