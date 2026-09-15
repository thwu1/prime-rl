#!/bin/bash


# Copy solution files to /app
cp /solution/parametric_dfa.py /app/parametric_dfa.py
cp /solution/run_queries.py /app/run_queries.py

# Run queries
cd /app && python3 run_queries.py
