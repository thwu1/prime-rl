#!/bin/bash

cd /app
python3 /solution/regime_analyzer.py
cp /solution/build_report.sh /app/build_report.sh
chmod +x /app/build_report.sh
/app/build_report.sh
