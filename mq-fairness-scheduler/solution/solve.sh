#!/bin/bash

# Install the reference scheduler implementation
cp /solution/scheduler_impl.py /app/scheduler.py

# Run all six simulation scenarios
cd /app
mkdir -p results
python3 main.py scenarios/uniform.json results/uniform.json
python3 main.py scenarios/skewed.json results/skewed.json
python3 main.py scenarios/weighted.json results/weighted.json
python3 main.py scenarios/demand_limited.json results/demand_limited.json
python3 main.py scenarios/dynamic.json results/dynamic.json
python3 main.py scenarios/cascade.json results/cascade.json

# Generate tc configuration script
cp /solution/tc_config.sh /app/tc_config.sh
chmod +x /app/tc_config.sh

# Generate aggregate script and run it
cp /solution/aggregate.sh /app/aggregate.sh
chmod +x /app/aggregate.sh
/app/aggregate.sh
