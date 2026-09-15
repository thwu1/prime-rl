#!/bin/bash

# Install dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 pyyaml==6.0.2 -q

# Deploy the corrected optimizer
cp /solution/optimizer.py /app/optimizer.py

# Deploy the evaluation tool
cp /solution/evaluate.py /app/evaluate.py

# Deploy the covariance recovery tool
cp /solution/covariance.py /app/covariance.py

# Deploy the consistency analyzer
cp /solution/consistency.py /app/consistency.py

# Deploy the visualization pipeline and helper
cp /solution/pipeline.sh /app/pipeline.sh
chmod +x /app/pipeline.sh
cp /solution/gen_dot.py /app/gen_dot.py

# Verify by running the full pipeline on the clean graph
bash /app/pipeline.sh /app/graphs/square_loop.g2o /app/config_clean.yaml /app/output_clean

# Also verify the corrupted graph with robust loss
python3 /app/optimizer.py \
    --graph /app/graphs/corrupted_loop.g2o \
    --config /app/config_robust.yaml \
    --output /app/output_robust.txt

# Run consistency analysis on corrupted graph at ground truth
python3 /app/consistency.py \
    --graph /app/graphs/corrupted_loop.g2o \
    --poses /app/graphs/ground_truth.txt \
    --threshold 7.815 \
    --output /app/output_corrupt_consistency.json
