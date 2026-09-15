#!/bin/bash

cd /app

# Fix all five bugs, add TPSafety invariant, and complete the .cfg
python3 /solution/fix_spec.py

# Run TLC to verify the corrected specification
java -cp /app/tla2tools.jar tlc2.TLC \
    /app/TwoPhase.tla \
    -config /app/TwoPhase.cfg \
    -workers 1 \
    -cleanup 2>&1 | tee /tmp/tlc_output.txt

# Extract TLC statistics and write results.json
python3 /solution/extract_results.py
