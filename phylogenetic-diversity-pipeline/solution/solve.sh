#!/usr/bin/env bash

set -e

# Install dependencies
pip3 install scikit-bio==0.7.3 -q 2>/dev/null

# Copy solution script to /app and run it
cp /solution/analyze.py /app/analyze.py
cd /app
python3 /app/analyze.py
