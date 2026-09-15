#!/bin/bash

# Ensure evaluation data exists (fallback if Docker build layer was lost)
if [ ! -f /opt/semtab_data/config.json ]; then
    python3 /solution/setup_data.py
fi

cp /solution/evaluator.py /app/evaluate.py
cd /app
python3 /app/evaluate.py --data-dir /opt/semtab_data --output /app/results.json
