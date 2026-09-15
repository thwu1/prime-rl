#!/bin/bash

# Copy the complete flux implementations
cp /solution/fluxes_solution.py /app/fluxes.py

# Copy the fixed Makefile with completed jq/awk targets
cp /solution/Makefile.fixed /app/Makefile

# Run the full pipeline: simulation, then post-processing
cd /app
python3 run_study.py
make report
make validate
