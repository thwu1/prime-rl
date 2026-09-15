#!/bin/bash

set -e

pip3 install numpy==2.1.3 -q

# Fix all defects and extend the codebase
python3 /solution/fix_code.py

# Run the benchmark to produce results.json
cd /app && python3 benchmark.py

# Generate convergence plot and work-precision CSV
python3 /solution/post_analysis.py
