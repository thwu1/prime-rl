#!/bin/bash

cd /app

# Copy solver and run it (creates /app/result.json)
cp /solution/cpd_solver.py /app/register.py
python3 /app/register.py
