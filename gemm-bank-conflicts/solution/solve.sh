#!/bin/bash

# Build the C shared library
make -C /app/src

# Deploy and run the analysis
cp /solution/bank_conflicts.py /app/bank_conflicts.py
cd /app
python3 bank_conflicts.py
