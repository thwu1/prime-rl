#!/bin/bash

set -e

cd /app

# Apply all fixes to dwarf_cfi.c
python3 /solution/apply_fixes.py

# Rebuild
make clean dwarf_cfi

echo "Solution applied and built successfully."
