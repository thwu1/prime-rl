#!/usr/bin/env bash

set -e

pip3 install pycparser==2.22 -q

cp /solution/scorer.py /app/scorer.py
chmod +x /app/scorer.py

cd /app
python3 /app/scorer.py /app/cases /app/results.json

echo "Results written to /app/results.json"
cat /app/results.json
