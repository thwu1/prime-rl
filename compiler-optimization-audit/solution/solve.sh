#!/bin/bash

set -e

# 1. Run the assembly analysis and produce /app/report.json
python3 /solution/analyze.py

# 2. Deploy the fixed accumulate function
cp /solution/fixed_accumulate.c /app/fixed_accumulate.c

# 3. Deploy the vectorized sum implementation
cp /solution/vectorized_sum.c /app/vectorized_sum.c

echo "Done. /app/report.json, /app/fixed_accumulate.c, and /app/vectorized_sum.c are ready."
