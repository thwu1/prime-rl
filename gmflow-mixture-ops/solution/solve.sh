#!/bin/bash

# Apply the fixed GM operations library
cp /solution/gm_ops_fixed.py /app/gm_ops.py

# Run the pipeline to generate results.json
cd /app && python3 pipeline.py
