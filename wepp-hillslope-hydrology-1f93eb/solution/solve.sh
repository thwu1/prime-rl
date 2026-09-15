#!/bin/bash

set -u
cd /app

# Copy solution files
cp /solution/wepp_pipeline.py /app/wepp_pipeline.py
cp /solution/Makefile /app/Makefile

# Remove old artifacts
rm -f /app/results.db /app/libgaml.so

# Compile Fortran library
make -C /app

# Ingest PAR files
for par in /app/stations/*.par; do
    python3 /app/wepp_pipeline.py ingest "$par"
done

# Simulate all scenarios
for scenario in /app/scenarios/*.json; do
    python3 /app/wepp_pipeline.py simulate "$scenario"
done

# Generate plots
for scenario in /app/scenarios/*.json; do
    python3 /app/wepp_pipeline.py plot "$scenario"
done
