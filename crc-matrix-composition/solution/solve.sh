#!/bin/bash

# Install dependencies
pip3 install amaranth==0.5.8 -q

# Deploy solution
cp /solution/crc_solver.py /app/crc_module.py

# Run to produce output files
cd /app
python3 /app/crc_module.py
