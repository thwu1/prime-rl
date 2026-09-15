#!/bin/bash

pip3 install pytrec_eval==0.5 rouge-score==0.1.2 -q

cd /app

# Deploy the implementation
cp /solution/solve_impl.py /app/mtrag_eval.py

# Evaluate system_a
mkdir -p /app/results
python3 /app/mtrag_eval.py evaluate \
    --input /app/data/input.jsonl \
    --predictions /app/data/predictions/system_a.jsonl \
    --qrels-dir /app/data/qrels \
    --output /app/results/system_a.json

# Evaluate system_b
python3 /app/mtrag_eval.py evaluate \
    --input /app/data/input.jsonl \
    --predictions /app/data/predictions/system_b.jsonl \
    --qrels-dir /app/data/qrels \
    --output /app/results/system_b.json

# Rank systems
python3 /app/mtrag_eval.py rank \
    --results-dir /app/results \
    --output /app/results/ranking.csv

# Compare systems
python3 /app/mtrag_eval.py compare \
    --result-a /app/results/system_a.json \
    --result-b /app/results/system_b.json \
    --output /app/results/comparison.json \
    --seed 42

echo "Solution complete."
