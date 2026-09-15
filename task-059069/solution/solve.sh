#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 pyyaml==6.0.2 h5py==3.12.1 -q

# Set up the solution
mkdir -p /app/src

# Copy the analysis module and entry point
cp /solution/gait_stability_pi.py /app/src/gait_stability_pi.py
cp /solution/run_pi.sh /app/run_pi
chmod +x /app/run_pi

# Run the pipeline
/app/run_pi /app/data /app/output

# Validate output against protocol specification
python3 /app/tools/validate_output.py /app/data /app/output
