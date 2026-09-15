#!/bin/bash

# Copy solution files to /app
cp /solution/anonymizer.py /app/anonymize.py
cp /solution/pipeline.sh /app/pipeline.sh
chmod +x /app/pipeline.sh

# Run the pipeline
cd /app
bash /app/pipeline.sh
