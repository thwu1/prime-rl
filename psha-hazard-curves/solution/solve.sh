#!/bin/bash

# Fix the 4 core pipeline bugs (mfd, distance, gmm, hazard)
python3 /solution/fix_pipeline.py

# Replace buggy disagg module with complete working version
cp /solution/disagg_fixed.py /app/pipeline/disagg.py

# Fix post-processing pipeline bugs (gnuplot, sqlite3, jq)
python3 /solution/fix_postprocess.py

# Run the pipeline to produce all output
cd /app && python3 -m pipeline.main
