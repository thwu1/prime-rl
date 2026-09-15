#!/bin/bash

pip3 install pyyaml==6.0.2 numpy==2.1.3 -q

# Deploy jq filter to required location
cp /solution/extract_rules.jq /app/pipeline/extract_rules.jq

# Run the evaluation pipeline
cd /app && python3 /solution/pipeline.py
