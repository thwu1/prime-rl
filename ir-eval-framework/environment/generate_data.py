#!/usr/bin/env python3
"""Generate synthetic MS MARCO-style IR evaluation data for the evaluation task."""
import random
import os

random.seed(20240315)

NUM_QUERIES = 150
PASSAGE_BASE = 500000
POOL_SIZE = 300
RUN_DEPTH = 50

os.makedirs('/app/data/runs', exist_ok=True)

# Generate qrels: each query has 1-3 relevant passages
qrels = {}
for qid in range(1000, 1000 + NUM_QUERIES):
    n_rel = random.choices([1, 2, 3], weights=[55, 35, 10])[0]
    base = PASSAGE_BASE + (qid - 1000) * POOL_SIZE
    pool = list(range(base, base + POOL_SIZE))
    qrels[qid] = sorted(random.sample(pool, n_rel))

# Write qrels in TREC format: qid  0  pid  1
with open('/app/data/qrels.tsv', 'w') as f:
    for qid in sorted(qrels):
        for pid in qrels[qid]:
            f.write(f"{qid}\t0\t{pid}\t1\n")

# System definitions: (name, quality_boost, corruption_type)
SYSTEMS = [
    ('bm25_baseline', 0.15, None),
    ('tfidf_rerank', 0.25, None),
    ('knrm_neural', 0.35, None),
    ('bert_small', 0.50, None),
    ('bert_large', 0.65, None),
    ('electra_rerank', 0.80, None),
    ('corrupt_format', 0.30, 'format'),
    ('dupl_pids', 0.45, 'duplicates'),
]


def make_ranking(qid, quality):
    """Generate a ranked list of passages for a query.

    Higher quality means relevant docs get larger score boosts,
    pushing them toward the top of the ranking.
    """
    base = PASSAGE_BASE + (qid - 1000) * POOL_SIZE
    pool = list(range(base, base + POOL_SIZE))
    rel = set(qrels[qid])
    scores = {}
    for pid in pool:
        s = random.random()
        if pid in rel:
            s += quality * (1.0 + random.random())
        scores[pid] = s
    return sorted(pool, key=lambda p: scores[p], reverse=True)[:RUN_DEPTH]


for name, quality, corrupt in SYSTEMS:
    with open(f'/app/data/runs/{name}.tsv', 'w') as f:
        for qid in sorted(qrels):
            ranking = make_ranking(qid, quality)
            if corrupt == 'format':
                for i, pid in enumerate(ranking):
                    rk = i + 1
                    r = random.random()
                    if r < 0.012:
                        # Spaces instead of tabs
                        f.write(f"{qid} {pid} {rk}\n")
                    elif r < 0.020:
                        # Extra column
                        f.write(f"{qid}\t{pid}\t{rk}\t{random.random():.4f}\n")
                    elif r < 0.025:
                        # Completely garbled line
                        f.write(f"INVALID_{random.randint(1, 9999)}\n")
                    else:
                        f.write(f"{qid}\t{pid}\t{rk}\n")
            elif corrupt == 'duplicates':
                for i, pid in enumerate(ranking):
                    rk = i + 1
                    f.write(f"{qid}\t{pid}\t{rk}\n")
                    # Occasionally duplicate a top-ranked PID at a later rank
                    if i < 10 and random.random() < 0.06:
                        dr = rk + random.randint(5, 20)
                        if dr <= RUN_DEPTH:
                            f.write(f"{qid}\t{pid}\t{dr}\n")
            else:
                for i, pid in enumerate(ranking):
                    f.write(f"{qid}\t{pid}\t{i + 1}\n")

print(f"Generated qrels for {len(qrels)} queries")
print(f"Generated {len(SYSTEMS)} run files")
