#!/bin/bash


# Copy solution files to /app
cp /solution/extract.sh /app/extract.sh
cp /solution/solver.py /app/solver.py
cp /solution/pipeline.sh /app/pipeline.sh
chmod +x /app/pipeline.sh /app/extract.sh

# Run the pipeline
bash /app/pipeline.sh
