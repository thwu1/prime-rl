#!/bin/bash

# Copy the taint analyzer to the expected location
cp /solution/analyzer.py /app/analyze.py

# Run the analyzer on the target webapp
python3 /app/analyze.py /app/webapp/app.py /app/results.json
