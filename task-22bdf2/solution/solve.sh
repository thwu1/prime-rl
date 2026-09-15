#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 -q

# Deploy solver
cp /solution/solver.py /app/solver.py

mkdir -p /app/output

# Run all scenarios
python3 /app/solver.py /app/scenarios/wind_tunnel.toml /app/output/wind_tunnel.npz
python3 /app/solver.py /app/scenarios/hydrostatic.toml /app/output/hydrostatic.npz
python3 /app/solver.py /app/scenarios/channel_flow.toml /app/output/channel_flow.npz
python3 /app/solver.py /app/scenarios/complex_flow.toml /app/output/complex_flow.npz
