#!/bin/bash

cp /solution/analyzer.py /app/analyzer.py
cp /solution/run_analysis.sh /app/run_analysis.sh
chmod +x /app/run_analysis.sh
cd /app
bash /app/run_analysis.sh
