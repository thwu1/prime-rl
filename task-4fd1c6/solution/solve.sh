#!/usr/bin/env bash

set -euo pipefail

# Run the solver to analyze the binary, generate exploit payloads,
# deploy the hardened sanitizer, and verify via the HTTP service
python3 /solution/solver.py
