#!/bin/bash

# Fix all pipeline bugs
python3 /solution/fix_pipeline.py

# Run the corrected pipeline
cd /app && python3 -m pipeline.run --input /app/dataset/pairs.json --output /app/output/results.json
