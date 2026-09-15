#!/bin/bash

# Replace the buggy pipeline with the corrected version
cp /solution/fixed_pipeline.py /app/pipeline.py

# Run the pipeline to produce detections.json
cd /app && python3 pipeline.py
