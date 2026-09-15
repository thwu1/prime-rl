#!/bin/bash

# Apply corrected implementations to the framework
cp /solution/fixed_cache_model.py /app/kernel_sim/cache_model.py
cp /solution/fixed_grid.py /app/kernel_sim/grid.py
cp /solution/fixed_hardware.py /app/kernel_sim/hardware.py
cp /solution/fixed_scheduler.py /app/kernel_sim/scheduler.py

# Run the analysis — computation produces /app/analysis.json
cd /app && python3 run_analysis.py
