#!/bin/bash

set -euo pipefail

python3 /solution/generate_fixed.py
chmod +x /app/runner-env.sh
