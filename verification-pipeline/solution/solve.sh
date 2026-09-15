#!/bin/bash


set -e

cp /solution/pipeline_impl.py /app/pipeline.py
chmod +x /app/pipeline.py

# Verify the solution loads and produces output
python3 /app/pipeline.py parse-sessions >/dev/null
python3 /app/pipeline.py parse-tests >/dev/null
python3 /app/pipeline.py cross-validate >/dev/null
