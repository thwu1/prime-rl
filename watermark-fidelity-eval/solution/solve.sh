#!/usr/bin/env bash

# Deploy watermark and evaluation scripts to /app/
cp /solution/watermark_impl.py /app/watermark.py
cp /solution/evaluate_impl.py /app/evaluate.py
chmod +x /app/watermark.py /app/evaluate.py

# Verify the pipeline works end-to-end
echo "Verifying watermark pipeline..."
python3 /app/watermark.py embed --key "verify-key-001" --input /app/data/corpus.jsonl --output /tmp/verify_wm.jsonl
python3 /app/watermark.py detect --key "verify-key-001" --input /tmp/verify_wm.jsonl --output /tmp/verify_det.jsonl
echo "Pipeline verification complete."
