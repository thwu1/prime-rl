"""Evaluate a heterogeneous multi-task retrieval benchmark."""

import json
import math
import os
from collections import defaultdict


def load_qrels(path):
    """Load TREC qrels file -> {(query_id, doc_id): relevance}."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 4:
                continue
            qid, _, did, rel = parts[0], parts[1], parts[2], int(parts[3])
            qrels[(qid, did)] = rel
    return qrels


def load_run(path):
    """Load TREC run file -> {query_id: [(doc_id, rank, score), ...]} sorted by rank."""
    run = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue
            qid = parts[0]
            did = parts[2]
            rank = int(parts[3])
            score = float(parts[4])
            run[qid].append((did, rank, score))
    for qid in run:
        run[qid].sort(key=lambda x: x[1])
    return dict(run)


def ndcg_at_k(qrels, run_results, qid, k=10):
    """Compute nDCG@k for a single query using graded relevance."""
    ranked = run_results.get(qid, [])[:k]

    # DCG: sum of (2^rel - 1) / log2(i+1) for positions 1..k
    dcg = 0.0
    for i, (did, _, _) in enumerate(ranked):
        rel = qrels.get((qid, did), 0)
        dcg += (2 ** rel - 1) / math.log2(i + 2)

    # IDCG: ideal ranking from all qrel judgments
    all_rels = sorted(
        [r for (q, _), r in qrels.items() if q == qid], reverse=True
    )[:k]
    idcg = 0.0
    for i, rel in enumerate(all_rels):
        idcg += (2 ** rel - 1) / math.log2(i + 2)

    if idcg == 0:
        return 0.0
    return dcg / idcg


def ap_at_k(qrels, run_results, qid, k=100):
    """Compute Average Precision@k for a single query (binary: rel >= 1)."""
    total_relevant = sum(1 for (q, _), r in qrels.items() if q == qid and r >= 1)
    if total_relevant == 0:
        return 0.0

    ranked = run_results.get(qid, [])[:k]
    num_rel_found = 0
    sum_precision = 0.0

    for i, (did, _, _) in enumerate(ranked):
        rel = qrels.get((qid, did), 0)
        if rel >= 1:
            num_rel_found += 1
            sum_precision += num_rel_found / (i + 1)

    return sum_precision / total_relevant


def mrr_at_k(qrels, run_results, qid, k=10):
    """Compute Reciprocal Rank@k for a single query (binary: rel >= 1)."""
    ranked = run_results.get(qid, [])[:k]
    for i, (did, _, _) in enumerate(ranked):
        if qrels.get((qid, did), 0) >= 1:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(qrels, run_results, qid, k=100):
    """Compute Recall@k for a single query (binary: rel >= 1)."""
    total_relevant = sum(1 for (q, _), r in qrels.items() if q == qid and r >= 1)
    if total_relevant == 0:
        return 0.0

    ranked = run_results.get(qid, [])[:k]
    retrieved_relevant = sum(
        1 for did, _, _ in ranked if qrels.get((qid, did), 0) >= 1
    )
    return retrieved_relevant / total_relevant


def evaluate_task(qrels, run_results, query_ids):
    """Compute all metrics macro-averaged over queries for one (task, system) pair."""
    per_query = {
        "ndcg@10": [],
        "map@100": [],
        "mrr@10": [],
        "recall@100": [],
    }

    for qid in query_ids:
        per_query["ndcg@10"].append(ndcg_at_k(qrels, run_results, qid, 10))
        per_query["map@100"].append(ap_at_k(qrels, run_results, qid, 100))
        per_query["mrr@10"].append(mrr_at_k(qrels, run_results, qid, 10))
        per_query["recall@100"].append(recall_at_k(qrels, run_results, qid, 100))

    return {m: sum(v) / len(v) for m, v in per_query.items()}


def main():
    bench_dir = "/opt/benchmark"

    with open(os.path.join(bench_dir, "tasks.json")) as f:
        task_meta = json.load(f)

    per_task = {}
    domain_tasks = defaultdict(list)

    for task_id in sorted(task_meta.keys()):
        domain = task_meta[task_id]["domain"]
        domain_tasks[domain].append(task_id)

        task_dir = os.path.join(bench_dir, "tasks", task_id)
        qrels = load_qrels(os.path.join(task_dir, "qrels.tsv"))
        query_ids = sorted(set(q for q, _ in qrels.keys()))

        task_results = {}
        for sys_label in ["a", "b"]:
            run = load_run(os.path.join(task_dir, f"run_{sys_label}.tsv"))
            task_results[f"system_{sys_label}"] = evaluate_task(qrels, run, query_ids)

        per_task[task_id] = task_results

    # Domain-level aggregation: macro-average over tasks
    per_domain = {}
    for domain in sorted(domain_tasks.keys()):
        per_domain[domain] = {}
        for sys_name in ["system_a", "system_b"]:
            dm = defaultdict(list)
            for tid in domain_tasks[domain]:
                for metric, value in per_task[tid][sys_name].items():
                    dm[metric].append(value)
            per_domain[domain][sys_name] = {
                m: sum(v) / len(v) for m, v in dm.items()
            }

    # Overall aggregation: macro-average over all tasks
    overall = {}
    all_tasks = sorted(task_meta.keys())
    for sys_name in ["system_a", "system_b"]:
        om = defaultdict(list)
        for tid in all_tasks:
            for metric, value in per_task[tid][sys_name].items():
                om[metric].append(value)
        overall[sys_name] = {m: sum(v) / len(v) for m, v in om.items()}

    # Long-tail tasks: both systems nDCG@10 < 0.3
    long_tail = sorted(
        tid
        for tid in per_task
        if per_task[tid]["system_a"]["ndcg@10"] < 0.3
        and per_task[tid]["system_b"]["ndcg@10"] < 0.3
    )

    # Difficulty ranking: ascending average nDCG@10, ties broken alphabetically
    difficulty_ranking = sorted(
        per_task.keys(),
        key=lambda t: (
            (per_task[t]["system_a"]["ndcg@10"] + per_task[t]["system_b"]["ndcg@10"])
            / 2,
            t,
        ),
    )

    result = {
        "per_task": per_task,
        "per_domain": per_domain,
        "overall": overall,
        "long_tail_tasks": long_tail,
        "task_difficulty_ranking": difficulty_ranking,
    }

    with open("/app/evaluation_report.json", "w") as f:
        json.dump(result, f, indent=2)

    print("Evaluation report written to /app/evaluation_report.json")


if __name__ == "__main__":
    main()
