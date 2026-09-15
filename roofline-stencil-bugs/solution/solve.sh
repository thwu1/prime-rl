#!/usr/bin/env bash

set -euo pipefail

# Restore original buggy files from the Docker image backup
cp /opt/hpc_framework/*.py /app/
cp /opt/hpc_framework/configs/*.json /app/configs/
cp /opt/hpc_framework/Makefile /app/
cp /opt/hpc_framework/kernels/*.c /app/kernels/

# Apply all fixes and implement missing components
python3 /solution/fix_and_implement.py

# Build the C kernel shared library
make -C /app clean all

# Run the analysis pipeline to produce results.json
cd /app
python3 /app/analyze.py
