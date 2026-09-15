#!/usr/bin/env bash
set -e
cd /app
mkdir -p /tmp/pipeline /app/output
python3 /app/pipeline/extract.py
python3 /app/pipeline/evaluate.py
python3 /app/pipeline/detect.py
python3 /app/pipeline/report.py
