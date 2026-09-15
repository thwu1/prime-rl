#!/bin/bash

python3 /solution/fix_pipeline.py
cd /app && /app/pipeline/run_analysis.sh
