#!/bin/bash

pip3 install numpy==2.1.3 -q

# Apply all fixes
cp /solution/pressure_fixed.py /app/fluid/pressure.py
cp /solution/advection_fixed.py /app/fluid/advection.py
cp /solution/forces_fixed.py /app/fluid/forces.py

# Verify by running the simulation
cd /app && python3 run_simulation.py
