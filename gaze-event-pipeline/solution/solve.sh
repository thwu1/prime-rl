#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 -q

# Copy reference solution to /app
cp /solution/gaze_pipeline.py /app/gaze_pipeline.py
