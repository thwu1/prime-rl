#!/bin/bash

set -e

# Deploy fixed engine
cp /solution/rubric_engine.py /app/rubric_engine.py

# Deploy pipeline script
cp /solution/analyze.sh /app/analyze.sh
chmod +x /app/analyze.sh

# Run the pipeline to create the database
cd /app
bash /app/analyze.sh

# Verify the engine works
python3 /app/rubric_engine.py score \
    --rubric /app/data/rubrics/paper_alpha.json \
    --grades /app/data/grades/paper_alpha.json
