#!/bin/bash

cd /app

# Restore baseline files if missing
cp -rn /opt/pipeline_task/* /app/ 2>/dev/null || true

# Generate the two header implementations
python3 /solution/implement_pipeline.py

# Build and validate
make clean && make
./trading_sim
