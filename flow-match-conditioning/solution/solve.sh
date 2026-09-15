#!/bin/bash

set -u

pip3 install numpy==2.1.3 pyyaml==6.0.2 pyzmq==26.2.0 -q

cd /app

# Fix pipeline bugs
python3 /solution/fix_pipeline.py

# Fix ZMQ server
python3 /solution/fix_server.py

# Install correct orchestrator
cp /solution/solve_impl.py /app/orchestrator.py

# Build plan database
python3 /app/orchestrator.py
