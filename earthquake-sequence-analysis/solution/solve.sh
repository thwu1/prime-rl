#!/bin/bash

# Install solution dependencies
pip3 install scipy==1.14.1 -q

# Copy solution pipeline to /app/
cp /solution/pipeline.py /app/pipeline.py

# Execute the pipeline
python3 /app/pipeline.py
