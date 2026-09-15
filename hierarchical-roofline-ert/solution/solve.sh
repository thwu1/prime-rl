#!/bin/bash

pip3 install numpy==2.1.3 -q

# Compile the C bandwidth-profile tool
gcc -O2 -o /app/ert_bw_profile /app/data/ert_bw_profile.c -lm

# Run it on the lowest-FLOP ERT data to produce the bandwidth profile
/app/ert_bw_profile /app/data/ert_raw/flop_001.dat /app/results/bw_profile.dat

# Run the Python analysis (produces JSON + gnuplot script)
python3 /solution/roofline_analysis.py

# Generate the roofline chart with gnuplot
gnuplot /app/results/roofline.gp
