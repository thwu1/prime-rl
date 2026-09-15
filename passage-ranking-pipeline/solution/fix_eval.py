#!/usr/bin/env python3
"""Fix the 4 bugs in the MS MARCO evaluation script.

Bug 1: MaxMRRRank = 5 (should be 10 for MRR@10)
Bug 2: Candidate rank indexing uses [rank] instead of [rank-1] (off-by-one)
Bug 3: Reciprocal rank formula uses 1/(i+2) instead of 1/(i+1)
Bug 4: MRR normalization divides by len(candidates) instead of len(qrels)
"""

with open("/app/eval/ms_marco_eval.py", "r") as f:
    content = f.read()

# Bug 1: MaxMRRRank should be 10, not 5
content = content.replace("MaxMRRRank = 5", "MaxMRRRank = 10")

# Bug 2: Rank indexing should be 0-based (rank-1), not 1-based (rank)
content = content.replace(
    "qid_to_ranked_candidate_passages[qid][rank] = pid",
    "qid_to_ranked_candidate_passages[qid][rank-1] = pid"
)

# Bug 3: Reciprocal rank should be 1/(i+1), not 1/(i+2)
content = content.replace(
    "MRR += 1.0 / (i + 2)",
    "MRR += 1.0 / (i + 1)"
)

# Bug 4: Normalize by number of judged queries, not submitted queries
content = content.replace(
    "MRR = MRR / len(qids_to_ranked_candidate_passages)",
    "MRR = MRR / len(qids_to_relevant_passageids)"
)

with open("/app/eval/ms_marco_eval_fixed.py", "w") as f:
    f.write(content)

print("Fixed evaluation script saved to /app/eval/ms_marco_eval_fixed.py")
