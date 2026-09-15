#!/bin/bash

# Deploy solution files to /app
cp /solution/converter.py /app/converter.py
cp /solution/migrate.py /app/migrate.py
cp /solution/pipeline.sh /app/pipeline.sh
chmod +x /app/pipeline.sh

# Run the full pipeline
bash /app/pipeline.sh
