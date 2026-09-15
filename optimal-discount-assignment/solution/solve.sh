#!/bin/bash

# Copy task files to working directory
cp /opt/pricing_task/supermarket.db /app/
cp /opt/pricing_task/main.py /app/

# Install the optimal pricing engine (replaces greedy with optimal solver)
cp /solution/optimal_pricing_engine.py /app/pricing_engine.py
