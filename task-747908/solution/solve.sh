#!/usr/bin/env bash

cd /app

# The solution consists of two files:
# 1. wcv_taumod.py - the WCV_TAUMOD module implementing the PVS specifications
# 2. process_encounters.py - encounter processing script

# Install no additional dependencies - pure Python only

# Deploy the WCV_TAUMOD module
cp /solution/wcv_solver.py /app/wcv_taumod.py

# Run the encounter processor
python3 /solution/process_encounters.py
