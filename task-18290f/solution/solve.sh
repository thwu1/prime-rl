#!/usr/bin/env bash

set -e

cd /app

pip3 install numpy==1.26.4 scipy==1.13.1 -q

# Generate samples if not already generated
if [ ! -d "/app/samples" ]; then
    python3 /app/generate_samples.py
fi

python3 /solution/sts_solver.py
