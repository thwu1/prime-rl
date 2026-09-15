#!/usr/bin/env bash

set -e

cp /solution/nekrs_auditor.py /app/nekrs_auditor.py

echo "Solution installed at /app/nekrs_auditor.py"
echo "Running quick validation..."
python3 /app/nekrs_auditor.py /app/cases/rbc_valid
