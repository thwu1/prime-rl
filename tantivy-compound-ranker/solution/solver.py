#!/usr/bin/env python3

"""
Solution: Implement NDCG evaluation and fix all search engine defects.

Strategy:
1. Implement DCG/NDCG@10 in the evaluation module to enable quality measurement
2. Run evaluation to establish baseline NDCG (expected: well below 0.80)
3. Diagnose defects by reading each pipeline module and applying BM25 expertise:
   - Data layer: db_reader.py uses INNER JOIN with metadata table, excluding
     documents without metadata rows (docs 21-25)
   - Config: k1=0.0 in config.json zeroes out term frequency sensitivity
   - Tokenizer: set() deduplication destroys term frequencies and document lengths
   - Index: global document frequency cross-contaminates per-field DF statistics
   - Scorer: IDF formula uses log(N/df) instead of BM25-standard formula
   - Searcher: max() aggregation discards multi-term/multi-field signal
4. Fix all defects, re-run, and verify NDCG@10 >= 0.80 for all queries
"""

import json
import math
import subprocess

# ============================================================
# Step 1: Implement NDCG evaluation module
# ============================================================

metrics_code = '''"""Information retrieval evaluation metrics."""

import math


def dcg_at_k(ranked_doc_ids, relevance_grades, k=10):
    """Compute Discounted Cumulative Gain at rank k.

    Uses standard gain: rel_i / log2(i + 1) for 1-indexed ranks.
    Documents not in relevance_grades have grade 0.
    """
    score = 0.0
    for i in range(min(k, len(ranked_doc_ids))):
        doc_id = int(ranked_doc_ids[i])
        rel = relevance_grades.get(doc_id, 0)
        score += rel / math.log2(i + 2)  # i=0 is rank 1 -> log2(2)
    return score


def ndcg_at_k(ranked_doc_ids, relevance_grades, k=10):
    """Compute Normalized Discounted Cumulative Gain at rank k.

    NDCG@k = DCG@k / IDCG@k where IDCG is DCG of ideal ranking.
    Returns 0.0 if no relevant documents exist (IDCG = 0).
    """
    dcg = dcg_at_k(ranked_doc_ids, relevance_grades, k)
    # Ideal ranking: sort documents by grade descending
    ideal_ids = sorted(relevance_grades.keys(), key=lambda d: -relevance_grades[d])
    idcg = dcg_at_k(ideal_ids, relevance_grades, k)
    if idcg == 0:
        return 0.0
    return dcg / idcg
'''

with open("/app/evaluation/metrics.py", "w") as f:
    f.write(metrics_code)
print("[1/7] Implemented NDCG@10 evaluation metrics")

# ============================================================
# Step 2: Fix data access — INNER JOIN excludes 5 documents
# ============================================================
# The document_metadata table only has entries for docs 1-20.
# INNER JOIN silently excludes docs 21-25 from indexing.

with open("/app/engine/db_reader.py") as f:
    src = f.read()
src = src.replace("INNER JOIN document_metadata", "LEFT JOIN document_metadata")
with open("/app/engine/db_reader.py", "w") as f:
    f.write(src)
print("[2/7] Fixed db_reader.py: INNER JOIN -> LEFT JOIN (all 25 docs indexed)")

# ============================================================
# Step 3: Fix BM25 parameters — k1=0 kills term frequency
# ============================================================
# k1=0 makes BM25 degenerate: TF_norm = TF/(TF+0) = 1.0 always,
# so term frequency has no impact on scoring.

with open("/app/engine/config.json") as f:
    config = json.load(f)
config["k1"] = 1.2
with open("/app/engine/config.json", "w") as f:
    json.dump(config, f, indent=2)
print("[3/7] Fixed config.json: k1=1.2 (standard BM25 parameter)")

# ============================================================
# Step 4: Fix tokenizer — set() deduplication destroys TF/DL
# ============================================================
# list(set(tokens)) removes duplicate tokens, making TF=1 for all terms
# and corrupting document length (DL = unique term count, not total).

with open("/app/engine/tokenizer.py") as f:
    src = f.read()
src = src.replace(
    "    # Remove duplicates to normalize token stream\n    return list(set(tokens))",
    "    return tokens",
)
with open("/app/engine/tokenizer.py", "w") as f:
    f.write(src)
print("[4/7] Fixed tokenizer.py: preserved token frequencies and document length")

# ============================================================
# Step 5: Fix index — global DF cross-contaminates fields
# ============================================================
# DF is computed globally across all fields instead of per-field.
# A term in 3 title docs + 2 body docs gets DF=3 for both fields,
# inflating body DF and deflating IDF for body matches.

with open("/app/engine/indexer.py") as f:
    src = f.read()

old_block = """        # Use global document frequency counts for all fields
        for field in fields:
            self.field_df[field] = {}
            for term in self.field_tf[field]:
                self.field_df[field][term] = len(global_term_docs.get(term, set()))"""

new_block = """        # Compute per-field document frequency from field-specific term data
        for field in fields:
            self.field_df[field] = {}
            for term, doc_dict in self.field_tf[field].items():
                self.field_df[field][term] = len(doc_dict)"""

src = src.replace(old_block, new_block)
with open("/app/engine/indexer.py", "w") as f:
    f.write(src)
print("[5/7] Fixed indexer.py: per-field document frequency computation")

# ============================================================
# Step 6: Fix scorer — incorrect IDF formula
# ============================================================
# Uses log(N/df) instead of BM25-standard log(1 + (N-df+0.5)/(df+0.5)).
# The standard formula provides better IDF saturation for common terms
# and handles edge cases (df near N) more gracefully.

with open("/app/engine/scorer.py") as f:
    src = f.read()
src = src.replace(
    "        return math.log(n / df)",
    "        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))",
)
with open("/app/engine/scorer.py", "w") as f:
    f.write(src)
print("[6/7] Fixed scorer.py: BM25-standard IDF with Lucene-style smoothing")

# ============================================================
# Step 7: Fix searcher — max() discards multi-term signal
# ============================================================
# Using max(scores) means only the highest-scoring term-field pair
# contributes to a document's final score. Documents matching multiple
# query terms get no benefit. sum() is the correct BM25 aggregation.

with open("/app/engine/searcher.py") as f:
    src = f.read()
src = src.replace(
    "            total_score = max(scores)",
    "            total_score = sum(scores)",
)
with open("/app/engine/searcher.py", "w") as f:
    f.write(src)
print("[7/7] Fixed searcher.py: sum-based score aggregation")

# ============================================================
# Verify: run pipeline and evaluate NDCG
# ============================================================

print("\n--- Running fixed pipeline ---")
r = subprocess.run(["make", "run"], capture_output=True, text=True, cwd="/app")
if r.returncode != 0:
    print(f"Pipeline failed:\nstdout: {r.stdout[:500]}\nstderr: {r.stderr[:500]}")
    raise SystemExit(1)
print("Pipeline executed successfully.")

print("\n--- Evaluating NDCG@10 ---")
r = subprocess.run(
    ["python3", "/app/evaluation/evaluate.py"],
    capture_output=True, text=True, cwd="/app",
)
print(r.stdout)
if r.returncode != 0:
    print(f"Evaluation failed: {r.stderr[:500]}")
    raise SystemExit(1)

print("\nAll defects fixed. NDCG targets met.")
