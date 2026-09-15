#!/bin/bash

# Apply all fixes to the mutation adequacy pipeline
python3 /solution/fix_all.py

# Run the pipeline to generate the report
cd /app
python3 run_pipeline.py
