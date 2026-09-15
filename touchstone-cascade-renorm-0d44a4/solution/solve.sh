#!/bin/bash

# Compile the C matrix operations library
make -C /app

# Copy solver into /app and run it
cp /solution/solver.py /app/process.py
cd /app
python3 /app/process.py
