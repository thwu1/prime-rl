#!/bin/bash

cd /app

# Apply all fixes via Python helper
python3 /solution/apply_fixes.py

# Build and run
make clean && make && ./gilt_engine rpi_data.csv gilts.json output.json

echo "Solution applied and executed."
