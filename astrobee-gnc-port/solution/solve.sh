#!/bin/bash

# Install dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Deploy solution
cp /solution/astrobee_ctl_sim.py /app/astrobee_ctl_sim.py

# Run simulation
cd /app
python3 astrobee_ctl_sim.py
