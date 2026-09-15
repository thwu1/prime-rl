#!/bin/bash

set -e

# Apply all physics corrections to the dust emission module
python3 /solution/apply_fixes.py

# Rebuild the corrected code
cd /app && make clean && make all
