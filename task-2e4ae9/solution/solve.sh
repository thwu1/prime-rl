#!/usr/bin/env bash

set -euo pipefail

pip3 install pytest==8.3.4 -q

cd /app

# Apply all fixes and generate analysis via the helper script
python3 /solution/solve_helper.py
