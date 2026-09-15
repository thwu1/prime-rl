#!/bin/bash

set -e

# Copy solution module to /app
cp /solution/solver.py /app/divunit.py

# Run the analysis to generate results.json, tables.db, and table_map.png
cd /app
python3 divunit.py
