#!/usr/bin/env bash

cd /app

# Apply all fixes across jq filters and Python scripts
python3 /solution/apply_fixes.py

# Clean stale intermediates and rebuild
make clean
make
