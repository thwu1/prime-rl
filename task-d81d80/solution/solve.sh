#!/bin/bash

# Fix the C and Python defects
python3 /solution/fix_code.py

# Recompile the C shared library
make -C /app clean
make -C /app

# Copy and run the filter evaluation
cp /solution/filter_evaluation.py /app/filter_evaluation.py
python3 /app/filter_evaluation.py

# Verify the corrected filter
python3 /app/run_slam.py
