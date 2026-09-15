#!/bin/bash

# End-to-end authenticated iperf3 test script.
# Starts an authenticated server, runs a client test as user alice,
# captures JSON output, and cleans up.

# Clean up any existing iperf3 processes
pkill -9 iperf3 2>/dev/null || true
sleep 1

# Start authenticated iperf3 server in daemon mode, one-off
iperf3 -s -D -1 -p 5201 \
    --rsa-private-key-path /app/auth/private.pem \
    --authorized-users-path /app/auth/credentials.csv

# Wait for server to be ready
sleep 2

# Run authenticated client test (3 seconds, JSON output)
IPERF3_PASSWORD=benchmark2024 iperf3 -c 127.0.0.1 -p 5201 \
    --username alice \
    --rsa-public-key-path /app/auth/public.pem \
    -t 3 -J > /app/auth_test_result.json 2>/dev/null

EXIT_CODE=$?

# Clean up server
pkill -9 iperf3 2>/dev/null || true

exit $EXIT_CODE
