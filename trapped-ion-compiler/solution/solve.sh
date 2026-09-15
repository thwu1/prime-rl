#!/bin/bash


set -e

# Install solution dependencies
pip3 install numpy==2.1.3 -q

# Copy solution files to /app
cp /solution/gates.py /app/gates.py
cp /solution/model.py /app/model.py
cp /solution/native_check_pass.py /app/native_check_pass.py
cp /solution/compile_pipeline.py /app/compile_pipeline.py

# Run the compilation pipeline
export PYTHONPATH=/app:${PYTHONPATH:-}
cd /app
python3 compile_pipeline.py
