#!/bin/bash

cd /app

# Copy and compile the C++ cost model
cp /solution/djolt_cost_model.cpp /app/djolt_cost_model.cpp
g++ -std=c++17 -O2 -o /app/djolt_cost_model /app/djolt_cost_model.cpp

# Compute hardware budgets for all three prefetchers
python3 /solution/budget_calculator.py

# Run multi-budget configuration sweep
python3 /solution/sweep.py
