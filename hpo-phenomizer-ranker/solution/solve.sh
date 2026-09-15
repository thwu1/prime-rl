#!/bin/bash

set -e

# Copy fixed pipeline components over the buggy ones
cp /solution/obo_graph_fixed.py /app/pipeline/obo_graph.py
cp /solution/process_annotations_fixed.awk /app/pipeline/process_annotations.awk
cp /solution/similarity_fixed.py /app/pipeline/similarity.py
cp /solution/run_pipeline_fixed.sh /app/pipeline/run_pipeline.sh

chmod +x /app/pipeline/run_pipeline.sh /app/pipeline/load_annotations.sh

# Run the fixed pipeline
bash /app/pipeline/run_pipeline.sh
