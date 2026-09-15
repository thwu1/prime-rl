#!/bin/bash

# Deploy corrected analysis and rebuild
cp /solution/solver.py /app/analysis.py
cd /app
rm -f results.json
python3 analysis.py
