#!/bin/bash

export PYBAMM_DISABLE_TELEMETRY=true
mkdir -p ~/.config/pybamm
printf 'pybamm:\n  enable_telemetry: false\n' > ~/.config/pybamm/config.yml

# pybamm is pre-installed in the Docker image
cp /solution/solve_helper.py /app/model_fidelity.py
python3 /app/model_fidelity.py
