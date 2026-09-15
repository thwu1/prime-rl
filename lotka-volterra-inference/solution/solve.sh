#!/bin/bash
set -e

# Install solution-only dependencies (pinned)
pip3 install numpy==2.1.3 pandas==2.2.3 cmdstanpy==1.2.4 -q

# Set up directories
mkdir -p /app/models /app/results

# Copy Stan model into place
cp /solution/lotka_volterra.stan /app/models/dynamics.stan

# Run the fitting script
python3 /solution/fit_model.py
