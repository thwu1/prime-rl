#!/bin/bash

cd /app

# Step 1: Generate differential flame graph SVG using the FlameGraph toolkit
mkdir -p /app/output
/app/FlameGraph/difffolded.pl /app/profiles/t0.folded /app/profiles/t4.folded \
    | /app/FlameGraph/flamegraph.pl --negate --title "Differential: t0 vs t4" \
    > /app/output/diff_t0_t4.svg

# Step 2: Run the analysis
python3 /solution/analyze.py
