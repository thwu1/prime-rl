#!/bin/bash

set -e

# Copy all fixed source files into place
cp /solution/fixed_implicit_weights.c /app/src/implicit_weights.c
cp /solution/fixed_Makefile /app/Makefile
cp /solution/fixed_collator.py /app/collator.py
cp /solution/fixed_register_collation.py /app/register_collation.py

# Build the C shared library
make -C /app clean || true
make -C /app

# Generate the sorted multilingual output via SQLite3 custom collation
cd /app
python3 register_collation.py

# Verify conformance
python3 run_conformance.py --limit 5000 --verbose
