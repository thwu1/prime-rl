#!/bin/bash

# Compile the C frame validation tools
cd /app/tools
make clean && make
cd /app

# Deploy the solution decoder and compatibility analyzer
cp /solution/decoder.py /app/decoder.py
cp /solution/analyze_compatibility.py /app/analyze_compatibility.py

# Run decoder to produce decoded_messages.json and frame_analysis.json
python3 /app/decoder.py

# Run compatibility analysis to produce compatibility_report.json
python3 /app/analyze_compatibility.py
