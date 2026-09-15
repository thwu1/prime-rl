#!/bin/bash

pip3 install numpy==1.26.4 -q

# Save original broken solver for comparison
cp /app/carbonate.py /app/carbonate_original.py

# Install fixed solver
cp /solution/carbonate_fixed.py /app/carbonate.py

# Install CLI batch tool
cp /solution/co2batch.py /app/co2batch.py

# Generate diagnosis report by comparing broken vs fixed
python3 /solution/generate_diagnosis.py
