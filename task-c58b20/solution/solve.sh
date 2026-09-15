#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Copy fixed simulator into place
cp /solution/fixed_simulator.py /app/simulator.py

# Run the simulator against all scenarios
cd /app
python3 /app/simulator.py
