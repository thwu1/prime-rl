#!/bin/bash

# No extra pip dependencies needed — exploit uses only stdlib

# Check if the server is already running (started by CMD)
if pgrep -x ground_station > /dev/null 2>&1; then
    echo "Server already running"
else
    echo "Starting server..."
    # Generate flag
    mkdir -p /app/secrets
    python3 -c "import os; print('FLAG{' + os.urandom(16).hex() + '}')" > /app/secrets/flag.txt

    # Start the ground station server with output redirected
    /app/ground_station > /dev/null 2>&1 &

    # Wait for server to be ready
    for i in $(seq 1 30); do
        python3 -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1)
try:
    s.connect(('127.0.0.1', 9090))
    s.close()
    sys.exit(0)
except:
    sys.exit(1)
" 2>/dev/null && break
        sleep 0.5
    done

    # Remove flag file — flag is now only in server memory
    rm -f /app/secrets/flag.txt
    echo "Server started"
fi

# Deploy and run the exploit
cp /solution/exploit.py /app/exploit.py
python3 /app/exploit.py
