#!/bin/bash

# Install dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Copy estimator module and run output generation
cp /solution/estimator.py /app/estimator.py
cd /app
python3 /solution/generate_outputs.py
