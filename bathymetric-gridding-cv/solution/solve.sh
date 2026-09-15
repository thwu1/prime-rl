#!/bin/bash

# Install solution dependencies (GMT CLI tools are pre-installed)
pip3 install numpy==1.26.4 pandas==2.2.2 -q

# Run the pipeline
cd /app
python3 /solution/pipeline.py
