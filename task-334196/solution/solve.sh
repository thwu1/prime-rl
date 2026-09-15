#!/bin/bash

# Apply all bug fixes, implement unset keyword, and generate conformance report
cd /app
python3 /solution/apply_fixes.py

# Verify engine runs successfully after fixes
python3 run.py > /dev/null 2>&1 && echo "Engine runs successfully after all fixes"

# Verify output matches expected
make diff > /dev/null 2>&1 && echo "Output matches v1.0 expected snapshot"
