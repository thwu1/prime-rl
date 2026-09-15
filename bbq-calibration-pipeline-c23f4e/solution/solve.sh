#!/bin/bash


set -euo pipefail

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Fix bugs and extend pipeline
python3 /solution/fix_and_extend.py

# Run the full pipeline
cd /app && make all
