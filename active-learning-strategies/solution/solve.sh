#!/usr/bin/env bash

set -e

pip3 install numpy==1.26.4 scipy==1.13.1 scikit-learn==1.5.2 small-text==1.4.1 -q

# Deploy corrected implementations
cp /solution/strategies_fixed.py /app/strategies.py
cp /solution/stopping_fixed.py /app/stopping.py
cp /solution/pipeline_fixed.py /app/pipeline.py

# Run the pipeline to generate results
cd /app && python3 pipeline.py
