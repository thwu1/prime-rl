#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Copy solution files to /app
cp /solution/analyze.sh /app/analyze.sh
cp /solution/parse_pm.py /app/parse_pm.py
cp /solution/forensic_analyzer.py /app/forensic_analyzer.py
chmod +x /app/analyze.sh

# Run the analysis pipeline
bash /app/analyze.sh
