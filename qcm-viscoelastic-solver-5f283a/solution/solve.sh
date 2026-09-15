#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Deploy engine and pipeline
cp /solution/qcm_engine_impl.py /app/qcm_engine.py
cp /solution/analyze_impl.py /app/analyze.py

# Run the analysis pipeline
cd /app && python3 /app/analyze.py

# Verify results file was created
if [ ! -f /app/results.json ]; then
    echo "ERROR: /app/results.json not created"
    exit 1
fi

echo "Pipeline completed. Results:"
cat /app/results.json
