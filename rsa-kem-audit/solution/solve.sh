#!/bin/bash

set -e

# Apply all fixes and write the audit report
python3 /solution/fix_kem.py

# Rebuild
cd /app
make clean
make all

# Verify the roundtrip test passes
./test_roundtrip

echo "Solution applied and verified successfully."
