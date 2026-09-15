#!/usr/bin/env python3
"""Okapi BM25 passage reranking over MS MARCO-style candidate lists.

Reads candidates from /app/data/top100.tsv, computes IDF from
/app/data/collection.tsv, scores with BM25, and outputs ranked run file.
"""

import math
import os
from collections import Counter, defaultdict


def tokenize(text):
    """Lowercase whitespace tokenization."""
    return text.lower().split()


# === Load collection for IDF computation ===
doc_count = 0
doc_freq = Counter()

with open("/app/data/collection.tsv") as f:
    for line in f:
        parts = line.strip().split('\t', 1)
        if len(parts) < 2:
            continue
        doc_count += 1
        tokens = set(tokenize(parts[1]))
        for token in tokens:
            doc_freq[token] += 1

# === Load candidates grouped by query ===
candidates_by_qid = defaultdict(list)
query_texts = {}

with open("/app/data/top100.tsv") as f:
    for line in f:
        parts = line.strip().split('\t', 3)
        if len(parts) < 4:
            continue
        qid = int(parts[0])
        pid = int(parts[1])
        query = parts[2]
        passage = parts[3]
        candidates_by_qid[qid].append((pid, passage))
        query_texts[qid] = query

# === Compute average document length across candidates ===
all_lengths = []
for cands in candidates_by_qid.values():
    for pid, passage in cands:
        all_lengths.append(len(tokenize(passage)))
avgdl = sum(all_lengths) / len(all_lengths) if all_lengths else 1.0

# === BM25 parameters ===
k1 = 1.2
b = 0.75


def bm25_score(query_tokens, passage_text):
    """Compute Okapi BM25 score for a passage given query tokens."""
    passage_tokens = tokenize(passage_text)
    dl = len(passage_tokens)
    tf_map = Counter(passage_tokens)

    score = 0.0
    for qt in query_tokens:
        if qt not in tf_map:
            continue
        tf = tf_map[qt]
        df = doc_freq.get(qt, 0)

        # BM25 IDF: log((N - df + 0.5) / (df + 0.5) + 1)
        idf = math.log((doc_count - df + 0.5) / (df + 0.5) + 1.0)

        # BM25 TF normalization
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))

        score += idf * tf_norm

    return score


# === Rank candidates and output run file ===
os.makedirs("/app/output", exist_ok=True)

with open("/app/output/run.tsv", "w") as f:
    for qid in sorted(candidates_by_qid.keys()):
        query_tokens = tokenize(query_texts[qid])

        scored = []
        for pid, passage in candidates_by_qid[qid]:
            s = bm25_score(query_tokens, passage)
            scored.append((s, pid))

        # Sort by score descending, tiebreak by PID ascending
        scored.sort(key=lambda x: (-x[0], x[1]))

        for rank, (score, pid) in enumerate(scored, 1):
            f.write(f"{qid}\t{pid}\t{rank}\n")

print("BM25 reranking complete. Run saved to /app/output/run.tsv")
