#!/bin/bash

# docdeid is pre-installed in the Docker image; install only if missing
pip3 install docdeid==1.0.1 -q 2>/dev/null

# Deploy pipeline to /app/
cp /solution/pipeline.py /app/pipeline.py
cp /solution/run_pipeline.sh /app/run_pipeline.sh
chmod +x /app/run_pipeline.sh

# Run the pipeline
bash /app/run_pipeline.sh
