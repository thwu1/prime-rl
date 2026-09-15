#!/bin/bash


pip3 install z3-solver==4.13.0.0 -q

# Ensure /app/ directory and intervals.py exist
mkdir -p /app
if [ ! -f /app/intervals.py ]; then
    cp /solution/intervals_original.py /app/intervals.py
fi

# Fix bugs and implement missing operations in intervals.py
python3 /solution/fix_intervals.py

# Install the Z3 verification framework
cp /solution/verifier.py /app/verifier.py

# Generate the verification report (also writes /app/laws.json)
python3 /solution/generate_report.py
