#!/bin/bash


# Copy the solver implementation into place and run it
cp /solution/ns_implementation.py /app/solver.py
cd /app
python3 /app/solver.py
