#!/bin/bash

set -e

cd /app

# Install runtime dependencies
pip3 install pytest==8.3.4 -q

# Fix the .coveragerc configuration (5 bugs)
python3 /solution/fix_config.py

# Remove any stale coverage data
rm -f /app/.coverage

# Run the test suite under coverage
coverage run -m pytest tests/ -q

# Analyze the coverage database
python3 /solution/analyze.py
