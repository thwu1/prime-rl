#!/bin/bash

pip3 install numpy==2.1.3 -q

# Deploy complete implementations
cp /solution/metrics_complete.py /app/metrics.py
cp /solution/run_pipeline_complete.sh /app/run_pipeline.sh
cp /solution/pipeline_complete.sql /app/pipeline.sql
chmod +x /app/run_pipeline.sh

# Run the pipeline
bash /app/run_pipeline.sh
