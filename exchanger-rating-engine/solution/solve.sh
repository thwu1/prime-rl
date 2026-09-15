#!/bin/bash

# Fix 1 & 2: Replace C source with corrected version and recompile
cp /solution/libcorr_fixed.c /app/libcorr.c
make -C /app

# Fix 3: Correct corrupted Taborek coefficient (90-deg, Re 1e3-1e4: a1 = 0.107)
sed -i 's/^90,1000,10000,0.170,/90,1000,10000,0.107,/' /app/coefficients.csv

# Fix 4 & 5: Replace Python rating tool with corrected version
cp /solution/hx_rate_fixed.py /app/hx_rate.py

# Verify all cases produce valid output
for case in /app/case1.json /app/case2.json /app/case3.json /app/case4.json; do
    echo "=== Rating $(basename $case) ==="
    python3 /app/hx_rate.py "$case"
    echo ""
done
