#!/bin/bash

set -e

# Restore the database to its initial broken state for clean analysis
cp /app/analytics.db.initial /app/analytics.db

# Generate repair.sql by analyzing the database
python3 /solution/solve_helper.py

# Apply the repair
sqlite3 /app/analytics.db < /app/repair.sql

echo "Repair applied successfully."
