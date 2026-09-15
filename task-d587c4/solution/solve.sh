#!/bin/bash

set -e

# Compile trec_eval from C source
echo "Compiling trec_eval..."
make -C /app/trec_eval_src

# Fix Bug 1: MaxMRRRank should be 10, not 9
sed -i 's/MaxMRRRank = 9/MaxMRRRank = 10/' /app/eval/msmarco_eval.py

# Fix Bug 2: Candidate array indexing should use rank-1 (0-based), not rank
sed -i 's/\[qid\]\[rank\] = pid/[qid][rank-1] = pid/' /app/eval/msmarco_eval.py

# Fix Bug 3: MRR denominator should use number of judged queries, not ranked
sed -i 's|MRR / len(qids_to_ranked_candidate_passages)|MRR / len(qids_to_relevant_passageids)|' /app/eval/msmarco_eval.py

# Fix Bug 4: Relevance grade filter - accept all rel > 0, not just rel == 1
sed -i 's/if int(l\[3\]) == 1:/if int(l[3]) > 0:/' /app/eval/msmarco_eval.py

# Verify eval script fix
echo "Verifying eval script fix on BM25 run..."
python3 /app/eval/msmarco_eval.py /app/data/qrels.txt /app/runs/bm25.tsv

# Run the full cross-tool evaluation pipeline
echo ""
echo "Running cross-tool evaluation pipeline..."
python3 /solution/pipeline.py
