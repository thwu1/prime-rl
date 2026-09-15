#!/bin/bash

# Install solution dependencies (numpy/scipy already in image, but pin for safety)
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Deploy the implementation
cp /solution/phase_noise_impl.py /app/framework/phase_noise.py

# Run the pipeline
cd /app
python3 run_pipeline.py
