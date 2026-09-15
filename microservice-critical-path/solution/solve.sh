#!/bin/bash

cp /solution/crisp_analyzer.py /app/crisp_analyzer.py

python3 /app/crisp_analyzer.py \
    --db /app/traces.db \
    --service gateway \
    --operation handleRequest \
    --output /app/results.json
