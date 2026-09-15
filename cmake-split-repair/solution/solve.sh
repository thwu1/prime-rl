#!/usr/bin/env bash

set -e

cd /app

# Create the solution helper that applies all fixes and creates the config package
python3 /solution/fix_project.py
