#!/bin/bash

set -e

cd /app

# Run the analysis and extraction
python3 /solution/analyze_tunnel.py

# Deploy the general-purpose detector
cp /solution/detector.py /app/detector.py
chmod +x /app/detector.py

echo "Solution complete."
