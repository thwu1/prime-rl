#!/bin/bash

pip3 install redis==5.0.3 -q

# Start Redis in daemon mode
redis-server --daemonize yes --save ""
sleep 2

# Load the production workload snapshot
python3 /app/setup/load_data.py

# Fix the profiler tool
cp /solution/profiler_fixed.py /app/tools/profiler.py

# Run the complete audit solution
python3 /solution/audit_solution.py
