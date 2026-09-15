#!/bin/bash

# Deploy the profiler solution
cp /solution/profiler.py /app/profiler.py

# Run the profiler to generate the report
python3 /app/profiler.py /app/capture.pcap /app/fingerprints.db /app/report.json
echo "Report generated at /app/report.json"
cat /app/report.json
