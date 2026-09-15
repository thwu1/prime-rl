#!/bin/bash

cd /app

# Copy solution files into place
cp /solution/regsho_auditor.py /app/regsho_auditor.py
cp /solution/pipeline.sh /app/pipeline.sh
chmod +x /app/pipeline.sh

# Run the pipeline (creates database + generates reports)
bash /app/pipeline.sh
