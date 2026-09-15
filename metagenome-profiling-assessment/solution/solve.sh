#!/bin/bash

# Copy solution files to /app
cp /solution/Makefile /app/Makefile
cp /solution/pipeline.py /app/pipeline.py

# Run the pipeline
cd /app
make all MANIFEST=/app/data/manifest.json OUTPUT_DIR=/app/output
