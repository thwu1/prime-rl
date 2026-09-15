#!/usr/bin/env bash

set -e

cd /app

# Apply all code fixes (Makefile, C bugs, Python bugs, geo Asian formula, CV integration)
python3 /solution/fix_engine.py

# Rebuild C shared library with corrected Makefile and source
make clean
make

# Run variance analysis to produce /app/variance_analysis.json
python3 /solution/variance_analyzer.py

# Verify the engine runs correctly
python3 main.py
