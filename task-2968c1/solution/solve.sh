#!/bin/bash

# Copy solution modules to /app
cp /solution/coverage_tracker.py /app/
cp /solution/greybox_fuzzer.py /app/
cp /solution/fault_localizer.py /app/
cp /solution/delta_debugger.py /app/
cp /solution/pipeline.py /app/

# Run the pipeline
cd /app
python3 pipeline.py
