#!/bin/bash

# Install solution dependencies
pip3 install numpy==1.26.4 scipy==1.13.1 -q

# Deploy the analysis pipeline
mkdir -p /app/crashdiag /app/results
cp /solution/crashdiag_main.py /app/crashdiag/main.py

# Run the pipeline
cd /app
python3 /app/crashdiag/main.py
