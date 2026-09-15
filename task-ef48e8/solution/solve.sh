#!/bin/bash

pip3 install numpy==1.26.4 -q

# Apply all fixes across Python, SQL loader, and R modules
python3 /solution/fix_scorer.py

# Run the evaluation pipeline
python3 /app/run_eval.py --output /app/output/scores.json
