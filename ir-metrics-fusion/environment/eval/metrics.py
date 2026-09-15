"""IR evaluation metrics module.

Provides standard information retrieval metrics for passage ranking evaluation.
All metrics operate on:
- qrels: dict mapping qid (int) -> {pid (int): relevance_grade (int)}
- run: dict mapping qid (int) -> [pid1, pid2, ...] (list of ints ordered by rank)

Relevance grades: 0 = not relevant, 1 = marginally relevant,
2 = relevant, 3 = highly relevant.
"""

import math
from collections import defaultdict


def load_qrels(path):
    """Load TREC-format qrels file.

    Format per line (tab-separated): qid  0  pid  relevance_grade
    Returns dict: qid -> {pid: grade}
    """
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            qid = int(parts[0])
            pid = int(parts[2])
            grade = int(parts[3])
            if qid not in qrels:
                qrels[qid] = {}
            qrels[qid][pid] = grade
    return qrels


def load_run(path):
    """Load a ranking run file.

    Format per line (tab-separated): qid  pid  rank
    Returns dict: qid -> [pid_at_rank_1, pid_at_rank_2, ...]
    """
    entries = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            qid = int(parts[0])
            pid = int(parts[1])
            rank = int(parts[2])
            entries.append((qid, pid, rank))
    entries.sort(key=lambda x: (x[0], x[2]))
    run = defaultdict(list)
    for qid, pid, rank in entries:
        run[qid].append(pid)
    return dict(run)


def compute_mrr_at_k(qrels, run, k):
    """Compute Mean Reciprocal Rank at k.

    For each query, find the rank of the first relevant passage within
    the top-k positions. MRR is the mean of 1/rank across all queries
    in the qrels (queries where no relevant passage appears in top-k
    contribute 0).
    """
    rr_sum = 0.0
    n_queries = len(qrels)
    for qid in qrels:
        if qid not in run:
            continue
        ranked_pids = run[qid]
        target_pid = list(qrels[qid].keys())[0]
        for i in range(min(k, len(ranked_pids))):
            if ranked_pids[i] == target_pid:
                rr_sum += 1.0 / (i + 1)
                break
    return rr_sum / n_queries


def compute_ndcg_at_k(qrels, run, k):
    """Compute Normalized Discounted Cumulative Gain at k.

    DCG@k  = sum_{i=1}^{k} (2^{rel_i} - 1) / log_2(i + 1)
    IDCG@k = DCG@k of the ideal (best possible) ranking
    nDCG@k = DCG@k / IDCG@k   (0 if IDCG@k == 0)
    """
    ndcg_sum = 0.0
    n_queries = len(qrels)
    for qid in qrels:
        if qid not in run:
            continue
        ranked_pids = run[qid]

        dcg = 0.0
        for i in range(min(k, len(ranked_pids))):
            pid = ranked_pids[i]
            rel = qrels[qid].get(pid, 0)
            dcg += (2 ** rel - 1) / math.log(i + 2)

        ideal_rels = sorted(qrels[qid].values())
        idcg = 0.0
        for i in range(min(k, len(ideal_rels))):
            idcg += (2 ** ideal_rels[i] - 1) / math.log(i + 2)

        if idcg > 0:
            ndcg_sum += dcg / idcg

    return ndcg_sum / n_queries


def compute_map_at_k(qrels, run, k):
    """Compute Mean Average Precision at k.

    For each query:
        AP@k = (1/R) * sum_{i=1}^{k} P(i) * rel(i)
    where R is the total number of relevant documents for the query,
    P(i) is precision at position i, and rel(i) is 1 if the document
    at position i is relevant (grade > 0), else 0.

    MAP@k = mean of AP@k across all queries in qrels.
    """
    raise NotImplementedError("MAP@k not yet implemented")


def compute_recall_at_k(qrels, run, k):
    """Compute Recall at k, averaged across queries.

    Recall@k = |{relevant docs in top-k}| / |{all relevant docs}|
    """
    raise NotImplementedError("Recall@k not yet implemented")
