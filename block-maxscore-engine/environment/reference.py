"""Exhaustive BM25 scorer — correct but slow reference implementation.

This scorer iterates through all postings for all query terms and computes
the exact BM25 score for every matching document. It serves as the ground
truth for verifying rank-safe implementations.
"""
import json
import sys
from collections import defaultdict

sys.path.insert(0, "/app")
from bm25 import bm25_term_score


def load_corpus(data_dir="/app/data"):
    """Load corpus and build a simple inverted index.

    Returns:
        index: dict mapping term -> sorted list of (doc_id, tf) tuples
        doc_lengths: dict mapping doc_id -> document length
        stats: dict with corpus statistics (num_docs, avg_doc_length)
    """
    index = defaultdict(list)
    doc_lengths = {}

    with open(f"{data_dir}/documents.jsonl") as f:
        for line in f:
            doc = json.loads(line)
            doc_id = doc["id"]
            terms = doc["terms"]
            doc_lengths[doc_id] = len(terms)

            tf_map = defaultdict(int)
            for t in terms:
                tf_map[t] += 1
            for t, tf in tf_map.items():
                index[t].append((doc_id, tf))

    for t in index:
        index[t].sort()

    with open(f"{data_dir}/stats.json") as f:
        stats = json.load(f)

    return dict(index), doc_lengths, stats


def exhaustive_search(index, doc_lengths, stats, query_terms, k):
    """Score every matching document and return the top-k.

    Args:
        index: inverted index from load_corpus()
        doc_lengths: document lengths from load_corpus()
        stats: corpus statistics from load_corpus()
        query_terms: list of query term strings
        k: number of top results to return

    Returns:
        List of (doc_id, score) tuples sorted by descending score,
        then ascending doc_id for ties.
    """
    N = stats["num_docs"]
    avgdl = stats["avg_doc_length"]

    # Deduplicate query terms
    seen = set()
    unique_terms = []
    for t in query_terms:
        if t not in seen:
            seen.add(t)
            unique_terms.append(t)

    scores = {}
    for term in unique_terms:
        if term not in index:
            continue
        df = len(index[term])
        for doc_id, tf in index[term]:
            dl = doc_lengths[doc_id]
            s = bm25_term_score(tf, df, N, dl, avgdl)
            scores[doc_id] = scores.get(doc_id, 0.0) + s

    results = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:k]
    return results
