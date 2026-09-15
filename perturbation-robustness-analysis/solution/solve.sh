#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Deploy and run the reference analyzer
cp /solution/analyzer.py /app/analyze.py

cd /app
python3 /app/analyze.py
