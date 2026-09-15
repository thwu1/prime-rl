#!/bin/bash

set -e

# Install dependencies
pip3 install numpy==2.1.3 -q

# Apply all fixes across the stack
python3 /solution/fix_bugs.py

# Run the corrected simulation
cd /app
python3 -m natcirc_sim
