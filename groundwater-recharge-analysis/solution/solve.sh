#!/bin/bash

set -e

# Install main dependencies (pinned). Transitive deps resolved by pip.
pip3 install pastas==1.14.0 pyet==1.5.0 -q

cd /app
python3 /solution/solve_analysis.py
