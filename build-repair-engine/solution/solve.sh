#!/usr/bin/env bash

set -e

# Install the repair engine where the task expects it
cp /solution/repair_engine.py /app/repair.py

# Run the engine to repair all provided subjects
python3 /app/repair.py
