#!/bin/bash

# Fix and compile the C dual-number library
cp /solution/Makefile /app/cdual/Makefile
make -C /app/cdual

# Deploy solution implementations
cp /solution/dual_c.py /app/dual_c.py
cp /solution/physics.py /app/physics.py
cp /solution/optimize.py /app/optimize.py

# Run the optimizer to produce result.json
cd /app && python3 optimize.py
