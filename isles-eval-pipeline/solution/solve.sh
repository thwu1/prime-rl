#!/bin/bash


# Install dependencies
pip3 install numpy==1.26.4 nibabel==5.2.1 scipy==1.13.1 -q

# Deploy the evaluation tool
cp /solution/evaluate.py /app/evaluate.py
chmod +x /app/evaluate.py

echo "Solution deployed: /app/evaluate.py"
