#!/usr/bin/env bash

set -e

# Build C diagnostic tools from source
cd /app/tools && make

# Run the corrected pipeline implementation
# (self-contained — does not depend on the buggy pipeline files)
python3 /solution/pipeline_impl.py

# Validate the output using the C comparison tool
echo ""
echo "=== Validating output with lut_compare ==="
/app/tools/lut_compare /app/output/dfg_lut.bin
