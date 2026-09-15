#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Copy fixed solver and fitting script
cp /solution/tmm_solver.py /app/tmm_solver.py
cp /solution/run_fit.py /app/run_fit.py

# Copy CLI tool and helper
cp /solution/tmm_cli.sh /app/tmm_cli.sh
chmod +x /app/tmm_cli.sh
cp /solution/tmm_cli_impl.py /app/tmm_cli_impl.py

# Run the fitting to produce results.json
cd /app && python3 run_fit.py
