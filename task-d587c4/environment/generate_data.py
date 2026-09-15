#!/usr/bin/env python3
"""Generate synthetic passage ranking evaluation data with graded relevance.

Creates deterministic qrels and system run files for an IR evaluation audit task.
Uses fixed seeds for reproducibility.
"""
import random
import bz2
import os
import sqlite3

SEED = 42
NUM_JUDGED = 200
NUM_EXTRA = 20
JUDGED_QIDS = list(range(100001, 100001 + NUM_JUDGED))
EXTRA_QIDS = list(range(200001, 200001 + NUM_EXTRA))
ALL_QIDS = JUDGED_QIDS + EXTRA_QIDS
NUM_CAND = 100

os.makedirs('/app/data', exist_ok=True)
os.makedirs('/app/runs', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

# Generate qrels: each judged query has exactly 1 relevant passage
# ~20% have graded relevance (rel=2 instead of rel=1)
rng_rel = random.Random(SEED + 999)
qrels = {}
qrels_grades = {}
for i, qid in enumerate(JUDGED_QIDS):
    pid = 1000001 + i
    qrels[qid] = pid
    if rng_rel.random() < 0.20:
        qrels_grades[qid] = 2  # highly relevant
    else:
        qrels_grades[qid] = 1  # relevant

# Write qrels in TREC format: qid\t0\tpid\trel
with open('/app/data/qrels.txt', 'w') as f:
    for qid in sorted(JUDGED_QIDS):
        f.write("{}\t0\t{}\t{}\n".format(qid, qrels[qid], qrels_grades[qid]))


def gen_run(all_qids, qrels, seed_off, top10p):
    """Generate a ranking run with deterministic placement of relevant passages."""
    rng = random.Random(SEED + seed_off)
    run = {}
    for qid in all_qids:
        entries = []
        used = set()
        rp = qrels.get(qid)
        rr = None
        if rp is not None:
            if rng.random() < top10p:
                rr = rng.randint(1, 10)
            else:
                rr = rng.randint(11, NUM_CAND)
            entries.append((rr, rp))
            used.add(rp)
        fb = 5000000 + (qid - 100000) * 500
        rank = 1
        fi = 0
        while len(entries) < NUM_CAND:
            if rank != rr:
                pid = fb + fi
                while pid in used:
                    fi += 1
                    pid = fb + fi
                entries.append((rank, pid))
                used.add(pid)
                fi += 1
            rank += 1
        entries.sort()
        run[qid] = entries[:NUM_CAND]
    return run


# Generate 4 system runs with increasing quality
bm25 = gen_run(ALL_QIDS, qrels, 100, 0.28)
tfidf = gen_run(ALL_QIDS, qrels, 200, 0.38)
knrm = gen_run(ALL_QIDS, qrels, 300, 0.52)
electra = gen_run(ALL_QIDS, qrels, 400, 0.68)

# BM25: plain MS MARCO format (qid\tpid\trank)
with open('/app/runs/bm25.tsv', 'w') as f:
    for qid in sorted(bm25):
        for r, p in bm25[qid]:
            f.write("{}\t{}\t{}\n".format(qid, p, r))

# TF-IDF: MS MARCO format with ~10% duplicate passage IDs
drng = random.Random(SEED + 500)
with open('/app/runs/tfidf.tsv', 'w') as f:
    for qid in sorted(tfidf):
        es = tfidf[qid]
        for r, p in es:
            f.write("{}\t{}\t{}\n".format(qid, p, r))
        if drng.random() < 0.10 and len(es) > 2:
            f.write("{}\t{}\t{}\n".format(qid, es[0][1], NUM_CAND + 1))

# KNRM: bz2-compressed MS MARCO format
with bz2.open('/app/runs/knrm.txt.bz2', 'wt') as f:
    for qid in sorted(knrm):
        for r, p in knrm[qid]:
            f.write("{}\t{}\t{}\n".format(qid, p, r))

# ELECTRA: TREC format (qid Q0 pid rank score run_name)
with open('/app/runs/electra.trec', 'w') as f:
    for qid in sorted(electra):
        for r, p in electra[qid]:
            s = round(1000.0 / r, 4)
            f.write("{}\tQ0\t{}\t{}\t{}\tELECTRA-base\n".format(qid, p, r, s))

# Create SQLite database with schema for cross-tool analysis
db = sqlite3.connect('/app/results.db')
db.execute('''CREATE TABLE IF NOT EXISTS per_query_scores (
    system_name TEXT NOT NULL,
    query_id INTEGER NOT NULL,
    tool TEXT NOT NULL,
    metric TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (system_name, query_id, tool, metric)
)''')
db.execute('''CREATE TABLE IF NOT EXISTS disagreements (
    system_name TEXT NOT NULL,
    query_id INTEGER NOT NULL,
    custom_score REAL NOT NULL,
    trec_eval_score REAL NOT NULL,
    abs_delta REAL NOT NULL,
    root_cause TEXT
)''')
db.execute('''CREATE TABLE IF NOT EXISTS summary (
    system_name TEXT NOT NULL,
    tool TEXT NOT NULL,
    metric TEXT NOT NULL,
    mean_score REAL NOT NULL,
    num_queries INTEGER NOT NULL,
    PRIMARY KEY (system_name, tool, metric)
)''')
db.commit()
db.close()

rel2_count = sum(1 for g in qrels_grades.values() if g == 2)
print("Data generation complete: {} judged queries ({} with rel=2), {} extra queries, 4 runs".format(
    NUM_JUDGED, rel2_count, NUM_EXTRA))
