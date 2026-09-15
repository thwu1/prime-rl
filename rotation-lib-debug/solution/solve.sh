#!/bin/bash

pip3 install matplotlib==3.9.2 -q

# Step 1: Fix rotation_lib.py bugs
python3 /solution/fix_bugs.py

# Step 2: Install working rotation_analysis.py
cp /solution/rotation_analysis_impl.py /app/rotation_analysis.py

# Step 3: Run calibration pipeline
python3 /solution/calibrate.py
