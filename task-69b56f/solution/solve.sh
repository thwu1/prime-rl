#!/bin/bash

# Analyze session transcripts and generate conformance report
python3 /solution/analyze_transcripts.py

# Deploy the conformant proxy implementation
cp /solution/proxy_impl.py /app/proxy.py

echo "Deployed: /app/conformance_report.json and /app/proxy.py"
