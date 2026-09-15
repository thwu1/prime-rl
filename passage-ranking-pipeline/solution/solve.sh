#!/bin/bash

set -e

# Step 1: Fix the evaluation script
python3 /solution/fix_eval.py

# Step 2: Implement BM25 reranking
python3 /solution/bm25_rerank.py

# Step 3: Create submission package
python3 /solution/create_submission.py

echo "All steps complete."
