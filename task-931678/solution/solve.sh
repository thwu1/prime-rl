#!/bin/bash

# Start the validation service in the background
python3 /app/validator/server.py &
SERVER_PID=$!
sleep 2

# Run the audit
python3 /solution/solver.py

# Clean up
kill $SERVER_PID 2>/dev/null
