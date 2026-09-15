#!/bin/bash
# Start the ARC API server in the background
python3 /app/api_server.py &
sleep 2
exec "$@"
