#!/bin/bash

cd /app

# Use trec_eval to get reference metrics for comparison with pipeline output
echo "=== Running trec_eval for reference ==="
for sys in bm25 tfidf embedding sparse hybrid; do
    echo "--- ${sys} ---"
    trec_eval -m ndcg_cut.10 -m map_cut.10 /app/data/qrels.txt /app/data/${sys}.run 2>/dev/null
done

echo ""
echo "=== Running buggy pipeline for comparison ==="
python3 /app/pipeline.py --output /tmp/pipeline_output.json

echo ""
echo "=== Running forensic audit solver ==="
python3 /solution/solver.py
