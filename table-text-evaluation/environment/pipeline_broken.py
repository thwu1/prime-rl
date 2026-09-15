#!/usr/bin/env python3
"""Table-Text Relatedness Evaluation Pipeline.


Evaluates relatedness between Wikipedia tables and text passages using
multiple scoring signals combined via rank fusion with cross-validated
threshold optimization.
"""

import csv
import json
import math
import os
import re
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────
def load_data(data_dir):
    """Load dataset from the specified data directory.

    Returns (tables_by_id, texts_by_id, pairs_df).
    """
    with open(os.path.join(data_dir, "tables.json")) as f:
        tables_list = json.load(f)
    with open(os.path.join(data_dir, "texts.json")) as f:
        texts_list = json.load(f)

    pairs_df = pd.read_csv(os.path.join(data_dir, "pairs.csv"), dtype=str)
    pairs_df["label"] = pairs_df["label"].astype(int)

    # Normalize column names to standard IR terminology
    pairs_df.columns = ["query_id", "doc_id", "label"]

    tables_dict = {t["id"]: t for t in tables_list}
    texts_dict = {t["text_id"]: t for t in texts_list}

    return tables_dict, texts_dict, pairs_df


# ─────────────────────────────────────────────────────────────────────────────
# Table serialization
# ─────────────────────────────────────────────────────────────────────────────
def serialize_table(table):
    """Convert a table dict to a flat text string for comparison."""
    return table.get("title", "")


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation metrics
# ─────────────────────────────────────────────────────────────────────────────
def compute_precision_at_k(relevance_list, k):
    """Precision at position k from a binary relevance list."""
    if k <= 0:
        return 0.0
    n = min(k, len(relevance_list))
    hits = sum(relevance_list[:k])
    return hits / n if n > 0 else 0.0


def compute_recall_at_k(relevance_list, k, total_relevant):
    """Recall at position k."""
    if total_relevant == 0:
        return 0.0
    hits = sum(relevance_list[:k])
    return hits / total_relevant


def compute_f1_at_k(relevance_list, k, total_relevant):
    """F1 score at position k — harmonic mean of P@k and R@k."""
    raise NotImplementedError("TODO: implement F1@k computation")


def compute_ndcg_at_k(relevance_list, k, total_relevant):
    """Normalized Discounted Cumulative Gain at k with binary relevance."""
    if total_relevant == 0:
        return 0.0

    n = min(k, len(relevance_list))
    dcg = sum(relevance_list[i] / math.log2(i + 1) for i in range(n))

    ideal_n = min(k, total_relevant)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(ideal_n))

    if idcg == 0:
        return 0.0
    return dcg / idcg


def compute_reciprocal_rank(relevance_list):
    """Reciprocal rank of the first relevant item."""
    for i, rel in enumerate(relevance_list):
        if rel:
            return 1.0 / i
    return 0.0


def compute_average_precision(relevance_list):
    """Average Precision for a single ranked list."""
    total = len(relevance_list)
    if total == 0:
        return 0.0

    cum_hits = 0
    ap = 0.0
    for i, rel in enumerate(relevance_list):
        if rel:
            cum_hits += 1
            ap += cum_hits / (i + 1)

    return ap / total


# ─────────────────────────────────────────────────────────────────────────────
# Reciprocal Rank Fusion
# ─────────────────────────────────────────────────────────────────────────────
def reciprocal_rank_fusion(rankings, k_rrf=60):
    """Combine multiple ranked lists using Reciprocal Rank Fusion.

    Args:
        rankings: {method_name: [doc_ids in ranked order]}
        k_rrf: smoothing constant (default 60)

    Returns:
        {doc_id: fused score}
    """
    scores = defaultdict(float)
    for _method, ranked_list in rankings.items():
        for rank_idx, doc_id in enumerate(ranked_list):
            scores[doc_id] += 1.0 / (k_rrf + rank_idx)
    return dict(scores)


# ─────────────────────────────────────────────────────────────────────────────
# BM25 scoring
# ─────────────────────────────────────────────────────────────────────────────
def compute_bm25_scores(tables_serialized, pairs_df, texts_dict, tables_dict,
                        k1=1.5, b=0.75):
    """Compute BM25 scores between text queries and serialized tables."""
    corpus = {tid: tables_serialized[tid].lower().split() for tid in tables_dict}
    doc_lengths = {tid: len(tokens) for tid, tokens in corpus.items()}
    avgdl = sum(doc_lengths.values()) / len(doc_lengths) if doc_lengths else 1
    N = len(corpus)

    df_counts = defaultdict(int)
    for tokens in corpus.values():
        for term in set(tokens):
            df_counts[term] += 1

    def idf(term):
        n = df_counts.get(term, 0)
        if n == 0:
            return 0.0
        return math.log(N / n)

    scores = {}
    for _, row in pairs_df.iterrows():
        tid = row["text_id"]
        tab_id = row["table_id"]
        query_terms = texts_dict.get(tid, {}).get("text", "").lower().split()
        doc_tokens = corpus.get(tab_id, [])
        dl = doc_lengths.get(tab_id, 0)

        tf_doc = defaultdict(int)
        for t in doc_tokens:
            tf_doc[t] += 1

        score = 0.0
        for term in query_terms:
            f = tf_doc.get(term, 0)
            if f > 0:
                score += idf(term) * (f * (k1 + 1)) / (
                    f + k1 * (1 - b + b * dl / avgdl)
                )

        scores[(tid, tab_id)] = score

    return scores


# ─────────────────────────────────────────────────────────────────────────────
# Grouped cross-validation
# ─────────────────────────────────────────────────────────────────────────────
def create_grouped_folds(pairs_df, n_folds=5):
    """Create grouped k-fold splits by text_id.

    Text IDs assigned round-robin to folds.
    Returns list of (train_indices, val_indices) tuples.
    """
    unique_tids = list(pairs_df["text_id"].unique())

    fold_map = {}
    for i, tid in enumerate(unique_tids):
        fold_map[tid] = i % n_folds

    folds = []
    for fold in range(n_folds):
        val_mask = pairs_df["text_id"].map(lambda x, f=fold: fold_map[x] == f)
        train_idx = pairs_df.index[~val_mask].tolist()
        val_idx = pairs_df.index[val_mask].tolist()
        folds.append((train_idx, val_idx))

    return folds


# ─────────────────────────────────────────────────────────────────────────────
# Scoring methods
# ─────────────────────────────────────────────────────────────────────────────
def _extract_capitalized_tokens(text):
    """Extract capitalized tokens for entity overlap scoring."""
    tokens = set()
    for word in text.split():
        cleaned = re.sub(r"[^\w]", "", word)
        if cleaned and cleaned[0].isupper() and len(cleaned) > 1:
            tokens.add(cleaned.lower())
    return tokens


def _url_score(text_obj, table_obj):
    return 1.0 if text_obj.get("url", "") == table_obj.get("url", "") else 0.0


def _entity_overlap_score(text_str, table_str):
    t_ents = _extract_capitalized_tokens(text_str)
    tab_ents = _extract_capitalized_tokens(table_str)
    union = t_ents | tab_ents
    if not union:
        return 0.0
    return len(t_ents & tab_ents) / len(union)


def _compute_tfidf_scores(tables_serialized, pairs_df, texts_dict, tables_dict):
    """Compute TF-IDF cosine similarity scores for all pairs."""
    all_docs = []
    doc_ids = []

    for tid in sorted(texts_dict.keys()):
        all_docs.append(texts_dict[tid]["text"])
        doc_ids.append(("text", tid))
    for tid in sorted(tables_dict.keys()):
        all_docs.append(tables_serialized[tid])
        doc_ids.append(("table", tid))

    vectorizer = TfidfVectorizer(max_features=5000, stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(all_docs)

    text_idx_map = {}
    table_idx_map = {}
    for idx, (dtype, did) in enumerate(doc_ids):
        if dtype == "text":
            text_idx_map[did] = idx
        else:
            table_idx_map[did] = idx

    scores = {}
    for _, row in pairs_df.iterrows():
        tid = row["text_id"]
        tab_id = row["table_id"]
        if tid in text_idx_map and tab_id in table_idx_map:
            sim = cosine_similarity(
                tfidf_matrix[text_idx_map[tid]], tfidf_matrix[table_idx_map[tab_id]]
            )[0][0]
            scores[(tid, tab_id)] = float(max(0, sim))
        else:
            scores[(tid, tab_id)] = 0.0

    return scores


# ─────────────────────────────────────────────────────────────────────────────
# Per-query evaluation
# ─────────────────────────────────────────────────────────────────────────────
def _evaluate_per_query(pairs_df, scores, k_values):
    """Compute per-query macro-averaged IR metrics."""
    metric_lists = {f"{m}_at_{k}": [] for k in k_values for m in ["p", "r", "f1", "ndcg"]}
    metric_lists["mrr"] = []

    for _text_id, group in pairs_df.groupby("text_id"):
        entries = [
            (row["table_id"], scores.get((row["text_id"], row["table_id"]), 0.0), row["label"])
            for _, row in group.iterrows()
        ]
        entries.sort(key=lambda x: -x[1])

        relevance = [int(e[2]) for e in entries]
        total_rel = sum(relevance)

        if total_rel == 0:
            continue

        for k in k_values:
            metric_lists[f"p_at_{k}"].append(compute_precision_at_k(relevance, k))
            metric_lists[f"r_at_{k}"].append(compute_recall_at_k(relevance, k, total_rel))
            metric_lists[f"f1_at_{k}"].append(compute_f1_at_k(relevance, k, total_rel))
            metric_lists[f"ndcg_at_{k}"].append(compute_ndcg_at_k(relevance, k, total_rel))

        metric_lists["mrr"].append(compute_reciprocal_rank(relevance))

    result = {}
    for key, values in metric_lists.items():
        result[key] = float(np.mean(values)) if values else 0.0
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────
def main():
    data_dir = "/app/data"
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)

    # Load data
    tables_dict, texts_dict, pairs_df = load_data(data_dir)

    # Serialize tables
    tables_ser = {tid: serialize_table(t) for tid, t in tables_dict.items()}

    # Compute per-method scores
    url_scores = {}
    entity_scores = {}

    for _, row in pairs_df.iterrows():
        tid, tab_id = row["text_id"], row["table_id"]
        text_obj = texts_dict.get(tid, {})
        table_obj = tables_dict.get(tab_id, {})

        url_scores[(tid, tab_id)] = _url_score(text_obj, table_obj)
        entity_scores[(tid, tab_id)] = _entity_overlap_score(
            text_obj.get("text", ""), tables_ser.get(tab_id, "")
        )

    tfidf_scores = _compute_tfidf_scores(tables_ser, pairs_df, texts_dict, tables_dict)

    # Combine via Reciprocal Rank Fusion
    all_pair_keys = list(
        set((row["text_id"], row["table_id"]) for _, row in pairs_df.iterrows())
    )

    url_ranked = sorted(all_pair_keys, key=lambda x: -url_scores.get(x, 0))
    ent_ranked = sorted(all_pair_keys, key=lambda x: -entity_scores.get(x, 0))
    tfidf_ranked = sorted(all_pair_keys, key=lambda x: -tfidf_scores.get(x, 0))

    rrf_raw = reciprocal_rank_fusion(
        {"url_matching": url_ranked, "entity_overlap": ent_ranked, "tfidf_cosine": tfidf_ranked},
        k_rrf=60,
    )

    # Normalize to [0, 1]
    if rrf_raw:
        max_s = max(rrf_raw.values())
        min_s = min(rrf_raw.values())
        if max_s > min_s:
            combined = {k: (v - min_s) / (max_s - min_s) for k, v in rrf_raw.items()}
        else:
            combined = {k: 0.5 for k in rrf_raw}
    else:
        combined = {}

    # Cross-validation with threshold grid search
    k_values = [5, 10, 20]
    n_folds = 5
    folds = create_grouped_folds(pairs_df, n_folds)

    thresholds = np.linspace(0.3, 0.9, 13)
    best_threshold = 0.5
    best_f1 = -1.0

    for threshold in thresholds:
        fold_f1s = []
        for train_idx, val_idx in folds:
            val_df = pairs_df.iloc[val_idx]
            val_scores = {
                (r["text_id"], r["table_id"]): combined.get((r["text_id"], r["table_id"]), 0.0)
                for _, r in val_df.iterrows()
            }
            m = _evaluate_per_query(val_df, val_scores, [10])
            fold_f1s.append(m.get("f1_at_10", 0.0))
        avg = float(np.mean(fold_f1s))
        if avg > best_f1:
            best_f1 = avg
            best_threshold = float(threshold)

    # Final evaluation
    final = _evaluate_per_query(pairs_df, combined, k_values)
    final["best_threshold"] = best_threshold

    # Write outputs
    with open(os.path.join(output_dir, "metrics.json"), "w") as f:
        json.dump(final, f, indent=2)

    with open(os.path.join(output_dir, "predictions.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["text_id", "table_id", "score"])
        writer.writeheader()
        for _, row in pairs_df.iterrows():
            pk = (row["text_id"], row["table_id"])
            writer.writerow(
                {
                    "text_id": row["text_id"],
                    "table_id": row["table_id"],
                    "score": f"{combined.get(pk, 0.0):.6f}",
                }
            )

    config = {
        "methods": ["url_matching", "entity_overlap", "tfidf_cosine"],
        "weights": [1.0, 1.0, 1.0],
        "threshold": best_threshold,
        "n_folds": n_folds,
        "k_values": k_values,
    }
    with open(os.path.join(output_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    print("Pipeline completed.")
    print(f"Best threshold: {best_threshold}")
    for k in k_values:
        print(
            f"  P@{k}={final[f'p_at_{k}']:.4f}  R@{k}={final[f'r_at_{k}']:.4f}  "
            f"F1@{k}={final[f'f1_at_{k}']:.4f}  NDCG@{k}={final[f'ndcg_at_{k}']:.4f}"
        )
    print(f"  MRR={final['mrr']:.4f}")


if __name__ == "__main__":
    main()
