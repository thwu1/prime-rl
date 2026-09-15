#!/bin/bash

pip3 install numpy==1.26.4 -q

# Run the complete solution: fault detection + robust EKF + outputs
python3 /solution/fix_and_run.py

# Generate trajectory comparison plot with gnuplot
gnuplot /solution/plot.gp
