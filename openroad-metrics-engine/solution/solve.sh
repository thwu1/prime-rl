#!/bin/bash

# Parse the Tcl source to generate metric_defs.json
python3 /solution/tcl_parser.py

# Install the metrics engine
cp /solution/solution.py /app/metrics_engine.py

# Verify the solution runs correctly
python3 /app/metrics_engine.py limits /app/designs/gcd_nangate45/golden.json > /dev/null 2>&1
python3 /app/metrics_engine.py check /app/designs/gcd_nangate45/golden.json /app/designs/gcd_nangate45/run1.json > /dev/null 2>&1
python3 /app/metrics_engine.py analyze /app/designs/gcd_nangate45/golden.json /app/designs/gcd_nangate45/run1.json /app/designs/gcd_nangate45/run2.json > /dev/null 2>&1
