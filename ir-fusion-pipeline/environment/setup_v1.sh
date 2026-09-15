#!/bin/bash
set -e

mkdir -p /app/runs

# Build index storing ONLY positions (deliberately omitting document vectors and raw content)
python3 -m pyserini.index.lucene \
  --collection JsonCollection \
  --input /app/corpus \
  --index /app/index_v1 \
  --generator DefaultLuceneDocumentGenerator \
  --threads 1 \
  --storePositions

# Run BM25 with Lucene-default parameters (k1=1.2, b=0.75)
# The pipeline log incorrectly claims k1=0.9, b=0.4
python3 -m pyserini.search.lucene \
  --index /app/index_v1 \
  --topics /app/queries.tsv \
  --output /app/runs/baseline_v1.txt \
  --hits 1000 \
  --bm25 --k1 1.2 --b 0.75
