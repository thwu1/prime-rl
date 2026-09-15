#!/bin/bash

# Fix C library bugs in roofline_core.c
# Bug 1: gb_to_bytes uses GiB (2^30 = 1073741824) instead of GB (1e9)
sed -i 's/1073741824\.0/1e9/' /app/roofline_core.c
# Bug 2: achievable_flops uses addition instead of min
sed -i 's/return mem_bound + peak_flops;/return fmin(mem_bound, peak_flops);/' /app/roofline_core.c

# Rebuild the shared library
cd /app && make clean && make

# Run the analysis engine to produce report.json
python3 /solution/engine.py
