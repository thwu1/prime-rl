#!/bin/bash

set -euo pipefail

cd /app

# Apply all bug fixes, install evaudit, and update Makefile
python3 /solution/fix_timing.py

# Rebuild all programs including evaudit
make clean && make

echo "All timing bugs fixed, evaudit created, programs rebuilt."
