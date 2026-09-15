#!/bin/bash

cd /app

# Start receiver daemon
python3 /app/receiver.py &
RECV_PID=$!
sleep 1

# Run attack
python3 /solution/attack.py

# Cleanup
kill $RECV_PID 2>/dev/null
wait $RECV_PID 2>/dev/null
