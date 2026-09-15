#!/bin/bash
set -e
cd /app
python3 -m pipeline.ingest
python3 -m pipeline.analyze
python3 -m pipeline.metrics
python3 -m pipeline.export
echo "Pipeline complete. Output at /app/output/scorecard.json"
