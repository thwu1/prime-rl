#!/bin/bash

cd /app

# Fix and build native engine, fix policies, implement SHiP
python3 /solution/fix_all.py

# Run evaluation
python3 /app/run_eval.py

# Generate policy ranking
python3 /solution/generate_ranking.py
