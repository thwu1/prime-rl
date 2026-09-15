"""Information retrieval metrics computation."""
import math


def compute_ndcg(qrels, results, k):
    """Compute nDCG@k for each query.

    Args:
        qrels: {query_id: {doc_id: relevance_score}}
        results: {query_id: {doc_id: retrieval_score}}
        k: cutoff value

    Returns:
        {query_id: ndcg_value}
    """
    ndcg_scores = {}

    for qid in results:
        if qid not in qrels:
            ndcg_scores[qid] = 0.0
            continue

        # Rank documents by retrieval score descending
        ranked = sorted(results[qid].items(), key=lambda x: x[1], reverse=True)[:k]

        # Compute DCG@k
        dcg = 0.0
        for i, (doc_id, _) in enumerate(ranked):
            rel = qrels[qid].get(doc_id, 0)
            dcg += rel / math.log2(i + 2)

        # Compute IDCG@k — ideal DCG with perfect ranking
        # NOTE: computes ideal from the retrieved docs' relevance values only
        ideal_rels = sorted(
            [qrels[qid].get(doc_id, 0) for doc_id, _ in ranked],
            reverse=True,
        )
        idcg = 0.0
        for i, rel in enumerate(ideal_rels):
            idcg += rel / math.log2(i + 2)

        ndcg_scores[qid] = dcg / idcg if idcg > 0 else 0.0

    return ndcg_scores


def compute_map(qrels, results, k):
    """Compute Average Precision at k for each query.

    Args:
        qrels: {query_id: {doc_id: relevance_score}}
        results: {query_id: {doc_id: retrieval_score}}
        k: cutoff value

    Returns:
        {query_id: average_precision_value}
    """
    ap_scores = {}

    for qid in results:
        if qid not in qrels:
            ap_scores[qid] = 0.0
            continue

        ranked = sorted(results[qid].items(), key=lambda x: x[1], reverse=True)[:k]

        relevant_seen = 0
        precision_sum = 0.0

        for i, (doc_id, _) in enumerate(ranked):
            if qrels[qid].get(doc_id, 0) > 0:
                relevant_seen += 1
                precision_sum += relevant_seen / (i + 1)

        # Average precision normalized by cutoff k
        ap_scores[qid] = precision_sum / k if k > 0 else 0.0

    return ap_scores


def compute_recall(qrels, results, k):
    """Compute Recall@k for each query."""
    recall_scores = {}

    for qid in results:
        if qid not in qrels:
            recall_scores[qid] = 0.0
            continue

        ranked = sorted(results[qid].items(), key=lambda x: x[1], reverse=True)[:k]
        retrieved_ids = {doc_id for doc_id, _ in ranked}

        total_relevant = sum(1 for v in qrels[qid].values() if v > 0)
        if total_relevant == 0:
            recall_scores[qid] = 0.0
            continue

        relevant_found = sum(
            1 for did in retrieved_ids if qrels[qid].get(did, 0) > 0
        )
        recall_scores[qid] = relevant_found / total_relevant

    return recall_scores


def compute_mrr(qrels, results):
    """Compute Mean Reciprocal Rank for each query."""
    rr_scores = {}

    for qid in results:
        if qid not in qrels:
            rr_scores[qid] = 0.0
            continue

        ranked = sorted(results[qid].items(), key=lambda x: x[1], reverse=True)

        rr = 0.0
        for i, (doc_id, _) in enumerate(ranked):
            if qrels[qid].get(doc_id, 0) > 0:
                rr = 1.0 / (i + 1)
                break

        rr_scores[qid] = rr

    return rr_scores
