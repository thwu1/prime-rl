#!/bin/bash

cd /app

# Create the package structure
mkdir -p /app/rail_sim

# Copy solution files into place (overwriting buggy versions)
cp /solution/states.py /app/rail_sim/states.py
cp /solution/speed_counter.py /app/rail_sim/speed_counter.py
cp /solution/state_machine.py /app/rail_sim/state_machine.py
cp /solution/motion_check.py /app/rail_sim/motion_check.py
cp /solution/simulator.py /app/rail_sim/simulator.py
cp /solution/trace.py /app/rail_sim/trace.py
cp /solution/__init__.py /app/rail_sim/__init__.py

# Copy the Makefile
cp /solution/Makefile /app/Makefile
