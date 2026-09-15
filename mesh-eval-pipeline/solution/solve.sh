#!/bin/bash

# Install dependencies
pip3 install numpy==1.26.4 trimesh==4.4.0 scipy==1.14.1 Rtree==1.3.0 -q

# Deploy corrected evaluation pipeline
cp /solution/evaluate_fixed.py /app/evaluate.py

# Run the evaluation
python3 /app/evaluate.py \
    --pairs /app/models/pairs.json \
    --samples 10000 \
    --voxel-res 32 \
    --seed 42 \
    --output /app/results.json
