#!/bin/bash

set -e

# Copy the corrected PID controller into place
cp /solution/pid_controller_fixed.c /app/pid_controller.c

# Build and run
cd /app
make clean
make
./sim_harness

echo "Solution complete. Trace written to /app/trace_output.csv"
