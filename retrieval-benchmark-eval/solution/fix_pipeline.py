#!/usr/bin/env python3
"""Corrected evaluation pipeline — fixes data parsing, metric computation,
and aggregation methodology."""

import json
import math
import os
from collections import defaultdict


def load_qrels(path):
    """Load TREC qrels with whitespace-robust parsing."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()  # FIX: split on any whitespace
            if len(parts) < 4:
                continue
            qid, _, did, rel = parts[0], parts[1], parts[2], int(parts[3])
            qrels[(qid, did)] = rel
    return qrels


def load_run(path):
    """Load TREC run with whitespace-robust parsing."""
    run = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()  # FIX: split on any whitespace
            if len(parts) < 6:
                continue
            qid = parts[0]
            did = parts[2]
            rank = int(parts[3])
            score = float(parts[4])
            run[qid].append((did, rank, score))
    for q in run:
        run[q].sort(key=lambda x: x[1])
    return dict(run)


def ndcg_at_k(qrels, run, query, k=10):
    results = run.get(query, [])[:k]
    dcg = sum(
        (2 ** qrels.get((query, did), 0) - 1) / math.log2(i + 2)
        for i, (did, _, _) in enumerate(results)
    )
    ideal_rels = sorted(
        [v for (q, _), v in qrels.items() if q == query], reverse=True
    )[:k]
    idcg = sum(
        (2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(ideal_rels)
    )
    return dcg / idcg if idcg > 0 else 0.0


def ap_at_k(qrels, run, query, k=100):
    total_rel = sum(1 for (q, _), v in qrels.items() if q == query and v >= 1)
    if total_rel == 0:
        return 0.0
    results = run.get(query, [])[:k]
    num_rel = 0
    sum_prec = 0.0
    for i, (did, _, _) in enumerate(results):
        if qrels.get((query, did), 0) >= 1:
            num_rel += 1
            sum_prec += num_rel / (i + 1)
    return sum_prec / total_rel  # FIX: use total_rel, not num_rel


def mrr_at_k(qrels, run, query, k=10):
    for i, (did, _, _) in enumerate(run.get(query, [])[:k]):
        if qrels.get((query, did), 0) >= 1:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(qrels, run, query, k=100):
    total_rel = sum(1 for (q, _), v in qrels.items() if q == query and v >= 1)
    if total_rel == 0:
        return 0.0
    return sum(
        1 for did, _, _ in run.get(query, [])[:k]
        if qrels.get((query, did), 0) >= 1
    ) / total_rel


def compute_task_metrics(qrels, run, queries):
    fns = {
        "ndcg@10": lambda q: ndcg_at_k(qrels, run, q, 10),
        "map@100": lambda q: ap_at_k(qrels, run, q, 100),
        "mrr@10": lambda q: mrr_at_k(qrels, run, q, 10),
        "recall@100": lambda q: recall_at_k(qrels, run, q, 100),
    }
    return {m: sum(f(q) for q in queries) / len(queries) for m, f in fns.items()}


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    bench_dir = config["benchmark_dir"]
    systems = config["systems"]

    with open(os.path.join(bench_dir, "tasks.json")) as f:
        meta = json.load(f)

    per_task = {}
    domain_tasks = defaultdict(list)

    for tid in sorted(meta):
        domain_tasks[meta[tid]["domain"]].append(tid)
        tdir = os.path.join(bench_dir, "tasks", tid)
        qrels = load_qrels(os.path.join(tdir, "qrels.tsv"))
        queries = sorted(set(q for q, _ in qrels))

        per_task[tid] = {}
        for sys_name in systems:
            sn = f"system_{sys_name}"
            run_path = os.path.join(tdir, f"run_{sys_name}.tsv")
            if not os.path.exists(run_path):
                per_task[tid][sn] = {
                    m: 0.0 for m in ["ndcg@10", "map@100", "mrr@10", "recall@100"]
                }
                continue
            run = load_run(run_path)
            per_task[tid][sn] = compute_task_metrics(qrels, run, queries)

    # FIX: Domain metrics use macro-averaging over tasks
    per_domain = {}
    for dom in sorted(domain_tasks):
        per_domain[dom] = {}
        for sn_short in systems:
            sn = f"system_{sn_short}"
            dm = defaultdict(list)
            for tid in domain_tasks[dom]:
                for m, v in per_task[tid][sn].items():
                    dm[m].append(v)
            per_domain[dom][sn] = {m: sum(v) / len(v) for m, v in dm.items()}

    # FIX: Overall metrics use macro-averaging over all tasks
    overall = {}
    for sn_short in systems:
        sn = f"system_{sn_short}"
        om = defaultdict(list)
        for tid in sorted(meta):
            for m, v in per_task[tid][sn].items():
                om[m].append(v)
        overall[sn] = {m: sum(v) / len(v) for m, v in om.items()}

    system_ranking = sorted(
        [f"system_{s}" for s in systems],
        key=lambda s: -overall[s]["ndcg@10"],
    )

    report = {
        "per_task": per_task,
        "per_domain": per_domain,
        "overall": overall,
        "system_ranking": system_ranking,
    }

    with open("/app/evaluation_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Corrected report written to /app/evaluation_report.json")


if __name__ == "__main__":
    main()
