#!/usr/bin/env python3
"""Evaluate retrieval systems across the multi-task benchmark."""
import json
import math
import os
from collections import defaultdict


def load_qrels(path):
    """Load TREC-format qrels file."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 4:
                continue
            qid = parts[0]
            did = parts[2]
            rel = int(parts[3])
            qrels[(qid, did)] = rel
    return qrels


def load_run(path):
    """Load TREC-format run file."""
    run = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
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
    """Compute nDCG@k for a single query."""
    results = run.get(query, [])[:k]
    dcg = 0.0
    for i, (did, _, _) in enumerate(results):
        rel = qrels.get((query, did), 0)
        dcg += rel / math.log2(i + 2)
    ideal_rels = sorted(
        [v for (q, _), v in qrels.items() if q == query], reverse=True
    )[:k]
    idcg = 0.0
    for i, r in enumerate(ideal_rels):
        idcg += r / math.log2(i + 2)
    return dcg / idcg if idcg > 0 else 0.0


def ap_at_k(qrels, run, query, k=100):
    """Compute Average Precision@k for a single query."""
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
    if num_rel == 0:
        return 0.0
    return sum_prec / num_rel


def mrr_at_k(qrels, run, query, k=10):
    """Compute Reciprocal Rank@k for a single query."""
    for i, (did, _, _) in enumerate(run.get(query, [])[:k]):
        if qrels.get((query, did), 0) >= 1:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(qrels, run, query, k=100):
    """Compute Recall@k for a single query."""
    total_rel = sum(1 for (q, _), v in qrels.items() if q == query and v >= 1)
    if total_rel == 0:
        return 0.0
    found = sum(
        1 for did, _, _ in run.get(query, [])[:k]
        if qrels.get((query, did), 0) >= 1
    )
    return found / total_rel


def compute_task_metrics(qrels, run, queries):
    """Compute averaged metrics for a task."""
    fns = [
        ("ndcg@10", lambda q: ndcg_at_k(qrels, run, q, 10)),
        ("map@100", lambda q: ap_at_k(qrels, run, q, 100)),
        ("mrr@10", lambda q: mrr_at_k(qrels, run, q, 10)),
        ("recall@100", lambda q: recall_at_k(qrels, run, q, 100)),
    ]
    metrics = {}
    for m_name, fn in fns:
        vals = [fn(q) for q in queries]
        metrics[m_name] = sum(vals) / len(vals) if vals else 0.0
    return metrics


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
            run_path = os.path.join(tdir, f"run_{sys_name}.tsv")
            if not os.path.exists(run_path):
                per_task[tid][f"system_{sys_name}"] = {
                    m: 0.0 for m in ["ndcg@10", "map@100", "mrr@10", "recall@100"]
                }
                continue
            run = load_run(run_path)
            per_task[tid][f"system_{sys_name}"] = compute_task_metrics(
                qrels, run, queries
            )

    # Per-domain: micro-average across all queries in domain
    per_domain = {}
    for dom in sorted(domain_tasks):
        per_domain[dom] = {}
        for sys_name in systems:
            sn = f"system_{sys_name}"
            all_scores = defaultdict(list)
            for tid in domain_tasks[dom]:
                tdir = os.path.join(bench_dir, "tasks", tid)
                qrels = load_qrels(os.path.join(tdir, "qrels.tsv"))
                queries = sorted(set(q for q, _ in qrels))
                run_path = os.path.join(tdir, f"run_{sys_name}.tsv")
                run = load_run(run_path) if os.path.exists(run_path) else {}
                for q in queries:
                    all_scores["ndcg@10"].append(ndcg_at_k(qrels, run, q, 10))
                    all_scores["map@100"].append(ap_at_k(qrels, run, q, 100))
                    all_scores["mrr@10"].append(mrr_at_k(qrels, run, q, 10))
                    all_scores["recall@100"].append(recall_at_k(qrels, run, q, 100))
            per_domain[dom][sn] = {
                m: sum(v) / len(v) if v else 0.0
                for m, v in all_scores.items()
            }

    # Overall: micro-average across all queries
    overall = {}
    for sys_name in systems:
        sn = f"system_{sys_name}"
        all_scores = defaultdict(list)
        for tid in sorted(meta):
            tdir = os.path.join(bench_dir, "tasks", tid)
            qrels = load_qrels(os.path.join(tdir, "qrels.tsv"))
            queries = sorted(set(q for q, _ in qrels))
            run_path = os.path.join(tdir, f"run_{sys_name}.tsv")
            run = load_run(run_path) if os.path.exists(run_path) else {}
            for q in queries:
                all_scores["ndcg@10"].append(ndcg_at_k(qrels, run, q, 10))
                all_scores["map@100"].append(ap_at_k(qrels, run, q, 100))
                all_scores["mrr@10"].append(mrr_at_k(qrels, run, q, 10))
                all_scores["recall@100"].append(recall_at_k(qrels, run, q, 100))
        overall[sn] = {
            m: sum(v) / len(v) if v else 0.0 for m, v in all_scores.items()
        }

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

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/current_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Evaluation report generated.")


if __name__ == "__main__":
    main()
