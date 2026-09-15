#!/bin/bash

# stim, pymatching, numpy already installed in Dockerfile

# Copy pipeline script to /app and run it
cp /solution/pipeline.py /app/qec_pipeline.py
cd /app && python3 /app/qec_pipeline.py
