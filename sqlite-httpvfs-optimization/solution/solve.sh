#!/bin/bash

set -e

# Generate the optimized index strategy
python3 /solution/solve_helper.py

# Apply the optimization
sqlite3 /app/analytics.db < /app/optimize.sql
