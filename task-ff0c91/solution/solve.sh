#!/bin/bash

set -e

# Install Python modules
mkdir -p /app/pipeline
cp /solution/garch.py /app/pipeline/garch.py
cp /solution/microstructure.py /app/pipeline/microstructure.py
cp /solution/regime.py /app/pipeline/regime.py
cp /solution/quoting.py /app/pipeline/quoting.py
cp /solution/risk.py /app/pipeline/risk.py
touch /app/pipeline/__init__.py

# Install pipeline runner
cp /solution/pipeline_runner.py /app/pipeline_runner.py

# Generate Makefile with proper tab indentation
python3 /solution/create_makefile.py

# Run the full pipeline
cd /app && make pipeline

echo "Pipeline complete."
