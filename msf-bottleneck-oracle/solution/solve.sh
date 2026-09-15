#!/bin/bash

cd /app

# Write the analysis script that the Makefile's analyze stage expects
cp /solution/analyze.py /app/pipeline/analyze.py

# Run the full pipeline: extract -> transform -> analyze -> visualize
make -C /app/pipeline all
