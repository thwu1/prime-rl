#!/bin/bash

# Restore framework files from staging (they may be missing if /app/ was mounted fresh)
cp -rn /opt/ir_task/* /app/ 2>/dev/null || true

# Install solution components
cp /solution/optimizer_impl.py /app/optimize.py
cp /solution/Makefile.solution /app/Makefile
cp /solution/gen_report.py /app/gen_report.py

# Run the full build pipeline
cd /app && make all
