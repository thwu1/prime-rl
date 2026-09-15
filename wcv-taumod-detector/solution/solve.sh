#!/bin/bash

set -e

cd /app

echo "Running WCV_taumod conflict detector..."
python3 /solution/wcv_solver.py

echo "Done. Results written to /app/output/results.json"
