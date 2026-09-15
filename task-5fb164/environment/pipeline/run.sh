#!/bin/bash
# Pipeline orchestrator: extract -> transform -> score
set -e
cd /app
echo "=== Stage 1: Extract and transform ==="
./pipeline/extract.sh
echo "=== Stage 2: Score ==="
python3 ./pipeline/score.py
echo "=== Pipeline complete ==="
