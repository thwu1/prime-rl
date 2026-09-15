#!/bin/bash

# Deploy solution files
cp /solution/scoring.c /app/scoring.c
cp /solution/Makefile /app/Makefile
cp /solution/solver.py /app/solver.py
cp /solution/pipeline.sh /app/pipeline.sh
chmod +x /app/pipeline.sh

# Run the pipeline (builds C library, runs solver, populates SQLite)
bash /app/pipeline.sh
