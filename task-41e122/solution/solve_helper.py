#!/usr/bin/env python3
"""Solution: BM25 multi-index forensics and rank fusion evaluation.

Strategy:
1. Load each CSC index and corpus; tokenize to compute per-doc term frequencies.
2. Grid-search over (method, k1, b) for each index, comparing expected BM25
   scores against stored values via MSE. Near-zero MSE identifies actual params.
3. Compute retrieval rankings from each index's CSC matrix.
4. Evaluate nDCG@10 for each index against provided relevance judgments.
5. Implement Reciprocal Rank Fusion (RRF) across all three indexes.
6. Optimize the RRF k parameter to maximize fusion nDCG@10.
7. Output structured results.
"""

import json
import math
import os
import re
from collections import Counter

import numpy as np


# ── Load shared data ─────────────────────────────────────────────────────

with open("/app/corpus.jsonl") as f:
    corpus = [json.loads(line)["text"] for line in f]

with open("/app/stopwords.json") as f:
    stopwords = set(json.load(f))

with open("/app/queries.json") as f:
    queries = json.load(f)

with open("/app/qrels.json") as f:
    qrels = json.load(f)

num_docs = len(corpus)


# ── Tokenize corpus ─────────────────────────────────────────────────────

split_fn = re.compile(r"(?u)\b\w\w+\b").findall


def tokenize(text):
    return [t for t in split_fn(text.lower()) if t not in stopwords]


corpus_tokens = [tokenize(doc) for doc in corpus]
doc_lengths = np.array([len(t) for t in corpus_tokens], dtype=np.float64)
avg_dl = float(doc_lengths.mean())

tf_per_doc = [Counter(t) for t in corpus_tokens]
doc_freq = Counter()
for tf_map in tf_per_doc:
    for token in tf_map:
        doc_freq[token] += 1


# ── BM25 variant formulas ───────────────────────────────────────────────

def idf_robertson(df, N):
    inner = (N - df + 0.5) / (df + 0.5)
    return math.log(max(inner, 1.0))


def idf_lucene(df, N):
    return math.log(1.0 + (N - df + 0.5) / (df + 0.5))


def idf_atire(df, N):
    return math.log(N / df)


def idf_bm25l(df, N):
    return math.log((N + 1) / (df + 0.5))


def idf_bm25plus(df, N):
    return math.log((N + 1) / df)


def tfc_robertson(tf, dl, avgdl, k1, b):
    return tf / (k1 * (1.0 - b + b * dl / avgdl) + tf)


def tfc_atire(tf, dl, avgdl, k1, b):
    return (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / avgdl))


def tfc_bm25l(tf, dl, avgdl, k1, b, delta=0.5):
    c = tf / (1.0 - b + b * dl / avgdl)
    return ((k1 + 1.0) * (c + delta)) / (k1 + c + delta)


def tfc_bm25plus(tf, dl, avgdl, k1, b, delta=0.5):
    num = (k1 + 1.0) * tf
    den = k1 * (1.0 - b + b * dl / avgdl) + tf
    return (num / den) + delta


IDF_FNS = {
    "robertson": idf_robertson,
    "lucene": idf_lucene,
    "atire": idf_atire,
    "bm25l": idf_bm25l,
    "bm25+": idf_bm25plus,
}

TFC_FNS = {
    "robertson": tfc_robertson,
    "lucene": tfc_robertson,  # same TFC as robertson
    "atire": tfc_atire,
    "bm25l": tfc_bm25l,
    "bm25+": tfc_bm25plus,
}


# ── Index identification via grid search ─────────────────────────────────

def identify_index(index_dir):
    """Identify BM25 variant and parameters from a CSC index."""
    with open(f"{index_dir}/vocab.index.json") as f:
        vocab = json.load(f)
    data = np.load(f"{index_dir}/data.csc.index.npy")
    indices = np.load(f"{index_dir}/indices.csc.index.npy")
    indptr = np.load(f"{index_dir}/indptr.csc.index.npy")

    # Sample entries from the CSC matrix
    samples = []
    for token_str, token_id in vocab.items():
        if token_str == "" or token_str not in doc_freq:
            continue
        start, end = int(indptr[token_id]), int(indptr[token_id + 1])
        for idx in range(start, end):
            doc_id = int(indices[idx])
            score = float(data[idx])
            tf = tf_per_doc[doc_id].get(token_str, 0)
            if tf > 0 and abs(score) > 1e-12:
                samples.append(
                    (doc_freq[token_str], tf, float(doc_lengths[doc_id]), score)
                )
        if len(samples) >= 300:
            break

    n_samples = min(200, len(samples))
    samples = samples[:n_samples]

    # Grid search over all variants and parameter ranges
    best_error = float("inf")
    best_method = None
    best_k1 = None
    best_b = None

    for method in ["robertson", "lucene", "atire", "bm25l", "bm25+"]:
        idf_fn = IDF_FNS[method]
        tfc_fn = TFC_FNS[method]
        needs_nonoccurrence = method in ("bm25l", "bm25+")

        for k1_x100 in range(50, 301, 5):
            k1 = k1_x100 / 100.0
            for b_x100 in range(0, 101, 2):
                b = b_x100 / 100.0
                mse = 0.0

                for df, tf, dl, stored_score in samples:
                    idf_val = idf_fn(df, num_docs)
                    if needs_nonoccurrence:
                        tfc_val = tfc_fn(tf, dl, avg_dl, k1, b)
                        nonoccurrence = idf_val * tfc_fn(0, avg_dl, avg_dl, k1, b)
                        expected = idf_val * tfc_val - nonoccurrence
                    else:
                        expected = idf_val * tfc_fn(tf, dl, avg_dl, k1, b)
                    mse += (expected - stored_score) ** 2

                mse /= n_samples
                if mse < best_error:
                    best_error = mse
                    best_method = method
                    best_k1 = round(k1, 2)
                    best_b = round(b, 2)

    return best_method, best_k1, best_b, vocab, data, indices, indptr


# ── Retrieval from CSC matrix ────────────────────────────────────────────

def retrieve_all_ranked(data, indices, indptr, vocab, query_text):
    """Retrieve all documents ranked by descending BM25 score."""
    tokens = tokenize(query_text)
    token_ids = [vocab[t] for t in tokens if t in vocab]
    scores = np.zeros(num_docs, dtype=np.float64)
    for tid in token_ids:
        start, end = int(indptr[tid]), int(indptr[tid + 1])
        scores[indices[start:end]] += data[start:end].astype(np.float64)
    return np.argsort(scores)[::-1].tolist()


# ── nDCG computation ─────────────────────────────────────────────────────

def compute_dcg(rels, k=10):
    """DCG@k = sum((2^rel - 1) / log2(i+1)) for 1-indexed positions."""
    dcg = 0.0
    for i, rel in enumerate(rels[:k]):
        dcg += (2 ** rel - 1) / math.log2(i + 2)
    return dcg


def compute_ndcg_single(ranked_doc_ids, qrel_dict, k=10):
    """Compute nDCG@k for a single query."""
    rels = [qrel_dict.get(str(did), 0) for did in ranked_doc_ids[:k]]
    dcg = compute_dcg(rels, k)
    ideal_rels = sorted(qrel_dict.values(), reverse=True)
    idcg = compute_dcg(ideal_rels, k)
    if idcg == 0:
        return 0.0
    return dcg / idcg


def compute_mean_ndcg(rankings_dict, qrels_dict, k=10):
    """Mean nDCG@k across all queries."""
    ndcgs = []
    for qi in range(len(queries)):
        qi_str = str(qi)
        ranking = rankings_dict[qi_str]
        qrel = qrels_dict.get(qi_str, {})
        ndcgs.append(compute_ndcg_single(ranking, qrel, k))
    return sum(ndcgs) / len(ndcgs)


# ── Reciprocal Rank Fusion ───────────────────────────────────────────────

def rrf_fusion(all_full_rankings, k_rrf, top_n=10):
    """
    Reciprocal Rank Fusion: RRF_score(d) = sum_s 1/(k + rank_s(d))
    Uses full rankings (all docs) from each system for accurate fusion.
    """
    fused = {}
    for qi in range(len(queries)):
        qi_str = str(qi)
        doc_scores = {}
        for sys_rankings in all_full_rankings.values():
            ranking = sys_rankings[qi_str]
            for rank_0, did in enumerate(ranking):
                rank_1 = rank_0 + 1  # 1-indexed
                doc_scores[did] = doc_scores.get(did, 0.0) + 1.0 / (k_rrf + rank_1)
        sorted_docs = sorted(doc_scores.keys(), key=lambda d: doc_scores[d], reverse=True)
        fused[qi_str] = sorted_docs[:top_n]
    return fused


# ── Main ─────────────────────────────────────────────────────────────────

print("=== BM25 Multi-Index Forensics ===\n")

# Step 1: Identify each index's variant and parameters
index_params = {}
index_components = {}  # Store CSC components for retrieval

for idx_name in ["a", "b", "c"]:
    idx_dir = f"/app/index_{idx_name}"
    print(f"Analyzing index {idx_name}...")
    method, k1, b, vocab, data, indices, indptr = identify_index(idx_dir)
    index_params[idx_name] = {"method": method, "k1": k1, "b": b}
    index_components[idx_name] = (vocab, data, indices, indptr)
    print(f"  Identified: method={method}, k1={k1}, b={b}")

# Step 2: Compute full retrieval rankings from each index
all_full_rankings = {}
for idx_name in ["a", "b", "c"]:
    vocab, data, indices, indptr = index_components[idx_name]
    rankings = {}
    for qi, q in enumerate(queries):
        rankings[str(qi)] = retrieve_all_ranked(data, indices, indptr, vocab, q)
    all_full_rankings[idx_name] = rankings

# Step 3: Compute nDCG@10 for each index
individual_ndcg = {}
for idx_name in ["a", "b", "c"]:
    # Use top-10 from full rankings for nDCG
    top10_rankings = {
        qi: r[:10] for qi, r in all_full_rankings[idx_name].items()
    }
    ndcg = compute_mean_ndcg(top10_rankings, qrels)
    individual_ndcg[idx_name] = round(ndcg, 6)
    print(f"  Index {idx_name} nDCG@10: {ndcg:.4f}")

best_individual = max(individual_ndcg, key=individual_ndcg.get)
print(f"\nBest individual: {best_individual} (nDCG={individual_ndcg[best_individual]:.4f})")

# Step 4: Optimize RRF k parameter
print("\nOptimizing RRF k parameter...")
best_k = 60
best_fusion_ndcg = 0.0

for k_val in [1, 2, 3, 5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 100, 150, 200, 300, 500]:
    fused = rrf_fusion(all_full_rankings, k_val)
    ndcg = compute_mean_ndcg(fused, qrels)
    if ndcg > best_fusion_ndcg:
        best_fusion_ndcg = ndcg
        best_k = k_val

print(f"Optimal RRF k={best_k}, fusion nDCG@10={best_fusion_ndcg:.4f}")

# Step 5: Compute final fusion rankings with optimal k
fusion_rankings = rrf_fusion(all_full_rankings, best_k)
fusion_ndcg = compute_mean_ndcg(fusion_rankings, qrels)

improvement = fusion_ndcg - individual_ndcg[best_individual]
print(f"Fusion improvement over best individual: {improvement:+.4f}")

# Step 6: Output results
output = {
    "indexes": index_params,
    "individual_ndcg": individual_ndcg,
    "best_individual": best_individual,
    "fusion_method": "rrf",
    "fusion_k": best_k,
    "fusion_ndcg": round(fusion_ndcg, 6),
    "fusion_rankings": fusion_rankings,
}

os.makedirs("/app/output", exist_ok=True)
with open("/app/output/results.json", "w") as f:
    json.dump(output, f, indent=2)

print("\nResults written to /app/output/results.json")
