#!/bin/bash

# Build the native cost model generator and produce cost_model.py
cd /app/native && make -s && ./cost_model_gen hw_spec.bin /app/cost_model.py

# Install the solution strategies
cp /solution/solution_strategies.py /app/strategies.py

# Run the test harness
bash /tests/test.sh
