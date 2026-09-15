#!/usr/bin/env bash

set -euo pipefail

pip3 install pint==0.24.4 PyYAML==6.0.2 -q

cd /app
python3 /solution/solve.py
