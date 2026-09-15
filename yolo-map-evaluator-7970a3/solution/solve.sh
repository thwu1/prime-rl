#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Generate dataset (creates SQLite database)
python3 /app/data/generate_dataset.py

# Deploy fixed pipeline components
cp /solution/extract.py /app/pipeline/extract.py
cp /solution/Makefile /app/Makefile
cp /solution/evaluate.py /app/evaluate.py

# Run the pipeline
make -C /app evaluate
