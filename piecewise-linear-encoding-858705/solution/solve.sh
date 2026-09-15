#!/bin/bash

pip3 install numpy==1.26.4 scikit-learn==1.4.2 -q

# Fix the buggy library files
cp /solution/bins_correct.py /app/ple/bins.py
cp /solution/encoder_correct.py /app/ple/encoder.py
cp /solution/cli_correct.py /app/ple_encode.py

# Create the Makefile pipeline
python3 /solution/create_makefile.py

# Install the report and sweep helpers
cp /solution/gen_report.py /app/gen_report.py
cp /solution/gen_sweep.py /app/gen_sweep.py

echo "Solution installed successfully."
