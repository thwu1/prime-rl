#!/bin/bash

cd /app
python3 /solution/analyze.py

if [ ! -f /app/audit_report.json ]; then
    echo "ERROR: analyze.py did not produce /app/audit_report.json"
    exit 1
fi
echo "Solution complete: /app/audit_report.json written"
