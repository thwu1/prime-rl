#!/bin/bash

set -e

# Restore EDN history files (agent may have modified /app/histories/)
python3 /solution/generate_histories.py

# Deploy solution files to /app/
cp /solution/edn_to_json.bb /app/edn_to_json.bb
cp /solution/linearizability_checker.py /app/linearizability_checker.py
cp /solution/viz_generator.py /app/viz_generator.py
cp /solution/analyze.sh /app/analyze.sh
chmod +x /app/analyze.sh /app/edn_to_json.bb

# Run the full analysis pipeline
cd /app
bash /app/analyze.sh
