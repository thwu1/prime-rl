#!/usr/bin/env python3
"""Generate TREC evaluation data with deliberate quality issues in run files."""

import json
import os
import random
from collections import defaultdict

SEED = 54321
NUM_QUERIES = 50
DOCS_PER_QUERY = 1000
DOC_POOL_SIZE = 50000


def main():
    os.makedirs("/app/runs", exist_ok=True)
    rng = random.Random(SEED)

    doc_ids = [f"D{i:06d}" for i in range(1, DOC_POOL_SIZE + 1)]

    # Multi-graded qrels: 2-4 relevant docs per query, grades 1-3
    qrels = {}
    for q in range(1, NUM_QUERIES + 1):
        qid = str(q)
        n_rel = rng.randint(2, 4)
        rdocs = rng.sample(doc_ids, n_rel)
        qrels[qid] = {d: rng.randint(1, 3) for d in rdocs}

    with open("/app/qrels.txt", "w") as f:
        for qid in sorted(qrels, key=int):
            for doc in sorted(qrels[qid]):
                f.write(f"{qid} 0 {doc} {qrels[qid][doc]}\n")

    # ---- helpers ----
    def make_run(offset, place):
        r = random.Random(SEED + offset)
        run = {}
        for q in range(1, NUM_QUERIES + 1):
            qid = str(q)
            rel = qrels[qid]
            rel_set = set(rel)
            pool = []
            seen = set(rel)
            need = DOCS_PER_QUERY - len(rel)
            while len(pool) < need:
                d = doc_ids[r.randint(0, DOC_POOL_SIZE - 1)]
                if d not in seen:
                    pool.append(d)
                    seen.add(d)
            for doc in sorted(rel):
                pos = place(q, rel[doc], r)
                pos = max(0, min(pos, len(pool)))
                pool.insert(pos, doc)
            pool = pool[:DOCS_PER_QUERY]
            entries = []
            for i, doc in enumerate(pool):
                sc = round(10000.0 - i * 10.0 + r.uniform(-0.005, 0.005), 4)
                entries.append((doc, i + 1, sc))
            run[qid] = entries
        return run

    # Each system excels on a different query subset so fusion improves
    def pl_alpha(q, g, r):
        if q % 5 in (0, 1):
            return r.randint(0, max(1, 10 - g * 3))
        return r.randint(80, 500)

    def pl_beta(q, g, r):
        if q % 5 == 2:
            return r.randint(0, max(1, 12 - g * 3))
        return r.randint(40, 300)

    def pl_gamma(q, g, r):
        if q % 5 == 3:
            return r.randint(0, max(1, 8 - g * 2))
        return r.randint(120, 700)

    def pl_delta(q, g, r):
        if q % 5 == 4:
            return r.randint(0, max(1, 15 - g * 4))
        return r.randint(60, 350)

    def pl_epsilon(q, g, r):
        if r.random() < 0.35:
            return r.randint(0, max(1, 6 - g))
        return r.randint(250, 900)

    runs = {
        "alpha": make_run(100, pl_alpha),
        "beta": make_run(200, pl_beta),
        "gamma": make_run(300, pl_gamma),
        "delta": make_run(400, pl_delta),
        "epsilon": make_run(500, pl_epsilon),
    }

    # ==== Write corrupted run files ====

    # ALPHA: duplicate doc entries for 10 random queries
    dup_rng = random.Random(SEED + 9001)
    dup_qs = set(dup_rng.sample(range(1, NUM_QUERIES + 1), 10))
    with open("/app/runs/run_alpha.txt", "w") as f:
        for qid in sorted(runs["alpha"], key=int):
            for doc, rank, sc in runs["alpha"][qid]:
                f.write(f"{qid} Q0 {doc} {rank} {sc:.4f} ALPHA\n")
            if int(qid) in dup_qs:
                nd = dup_rng.randint(3, 5)
                src = runs["alpha"][qid][:80]
                for doc, _, osc in dup_rng.sample(src, min(nd, len(src))):
                    nr = DOCS_PER_QUERY + dup_rng.randint(1, 20)
                    f.write(f"{qid} Q0 {doc} {nr} {osc - 9000:.4f} ALPHA\n")

    # BETA: 0-indexed ranks (0 through 999 instead of 1 through 1000)
    with open("/app/runs/run_beta.txt", "w") as f:
        for qid in sorted(runs["beta"], key=int):
            for doc, rank, sc in runs["beta"][qid]:
                f.write(f"{qid} Q0 {doc} {rank - 1} {sc:.4f} BETA\n")

    # GAMMA: score-rank inversion for 12 queries (ascending scores)
    inv_rng = random.Random(SEED + 9003)
    inv_qs = set(inv_rng.sample(range(1, NUM_QUERIES + 1), 12))
    with open("/app/runs/run_gamma.txt", "w") as f:
        for qid in sorted(runs["gamma"], key=int):
            entries = runs["gamma"][qid]
            if int(qid) in inv_qs:
                scores = [s for _, _, s in entries]
                scores.reverse()
                for i, (doc, rank, _) in enumerate(entries):
                    f.write(f"{qid} Q0 {doc} {rank} {scores[i]:.4f} GAMMA\n")
            else:
                for doc, rank, sc in entries:
                    f.write(f"{qid} Q0 {doc} {rank} {sc:.4f} GAMMA\n")

    # DELTA: zero-padded query IDs for ~35% of entries
    pad_rng = random.Random(SEED + 9004)
    with open("/app/runs/run_delta.txt", "w") as f:
        for qid in sorted(runs["delta"], key=int):
            for doc, rank, sc in runs["delta"][qid]:
                rv = pad_rng.random()
                if rv < 0.20:
                    pqid = f"{int(qid):03d}"
                elif rv < 0.35:
                    pqid = f"{int(qid):02d}"
                else:
                    pqid = qid
                f.write(f"{pqid} Q0 {doc} {rank} {sc:.4f} DELTA\n")

    # EPSILON: clean — no corruption
    with open("/app/runs/run_epsilon.txt", "w") as f:
        for qid in sorted(runs["epsilon"], key=int):
            for doc, rank, sc in runs["epsilon"][qid]:
                f.write(f"{qid} Q0 {doc} {rank} {sc:.4f} EPSILON\n")

    # ==== Write job specification ====
    job = {
        "description": "Evaluate retrieval systems, produce an improved combined ranking, and validate improvements statistically.",
        "qrels": "/app/qrels.txt",
        "runs_dir": "/app/runs/",
        "output_dir": "/app/output/",
        "eval_notes": "All metrics must follow standard trec_eval semantics.",
        "outputs": {
            "diagnostics": "diagnostics.json — for each run file keyed by system name (alpha, beta, gamma, delta, epsilon), list data quality issues found and corrections applied",
            "cleaned_runs": "cleaned_runs/ — corrected versions of all run files in standard TREC 6-column whitespace-delimited format (qid Q0 docid rank score run_id) with 1-indexed contiguous ranks, scores descending with rank, no duplicate documents per query, and query IDs matching the qrels file exactly",
            "per_system_eval": "eval_{system}.json for each of: alpha, beta, gamma, delta, epsilon — evaluation computed on the corresponding cleaned run",
            "combined_run": "combined.txt — TREC-format run file with run ID 'COMBINED' and up to 1000 results per query; the combined system must achieve strictly higher mean ndcg_cut_10 than every individual system",
            "combined_eval": "eval_combined.json — evaluation of the combined run in same format",
            "significance": "significance.json — paired statistical test comparing each individual system to the combined system using per-query ndcg_cut_10; keyed by system name, each entry has: test_name, statistic, p_value, significant_at_005"
        },
        "eval_format": {
            "per_query": {
                "<qid>": {
                    "ndcg_cut_10": 0, "ndcg_cut_100": 0, "ndcg_cut_1000": 0,
                    "map": 0, "recip_rank": 0, "recall_100": 0, "recall_1000": 0
                }
            },
            "mean": {
                "ndcg_cut_10": 0, "ndcg_cut_100": 0, "ndcg_cut_1000": 0,
                "map": 0, "recip_rank": 0, "recall_100": 0, "recall_1000": 0
            }
        }
    }
    with open("/app/job.json", "w") as f:
        json.dump(job, f, indent=2)


if __name__ == "__main__":
    main()
