#!/bin/bash

set -e

mkdir -p /app/runs /app/index

# Step 1: Diagnose the original pipeline
python3 /solution/diagnose.py

# Step 2: Build correct Lucene index with all stored fields
python3 -m pyserini.index.lucene \
  --collection JsonCollection \
  --input /app/corpus \
  --index /app/index \
  --generator DefaultLuceneDocumentGenerator \
  --threads 1 \
  --storePositions --storeDocvectors --storeRaw

# Step 3: BM25 default (k1=0.9, b=0.4)
python3 -m pyserini.search.lucene \
  --index /app/index \
  --topics /app/queries.tsv \
  --output /app/runs/bm25_default.txt \
  --hits 1000 \
  --bm25 --k1 0.9 --b 0.4

# Step 4: BM25 tuned (k1=2.0, b=0.75)
python3 -m pyserini.search.lucene \
  --index /app/index \
  --topics /app/queries.tsv \
  --output /app/runs/bm25_tuned.txt \
  --hits 1000 \
  --bm25 --k1 2.0 --b 0.75

# Step 5: BM25 + RM3 pseudo-relevance feedback
python3 -m pyserini.search.lucene \
  --index /app/index \
  --topics /app/queries.tsv \
  --output /app/runs/bm25_expanded.txt \
  --hits 1000 \
  --bm25 --rm3

# Step 6: Reciprocal Rank Fusion of all three runs
python3 -m pyserini.fusion \
  --runs /app/runs/bm25_default.txt /app/runs/bm25_tuned.txt /app/runs/bm25_expanded.txt \
  --output /app/runs/fused.txt \
  --method rrf

# Step 7: Evaluate all runs and perform term analysis
python3 /solution/analyze.py
