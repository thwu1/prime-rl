#!/bin/bash

set -e

###############################################################################
# Step 1: Fix the UB bug in scale_value()
###############################################################################
python3 /solution/fix_bug.py

###############################################################################
# Step 2: Run compiler comparison and build optimized
###############################################################################
python3 /solution/build_and_report.py

echo "Solution complete."
