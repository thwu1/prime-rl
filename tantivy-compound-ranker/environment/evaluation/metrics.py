"""Information retrieval evaluation metrics.

Implements standard IR evaluation metrics for measuring search ranking quality.
"""

import math


def dcg_at_k(ranked_doc_ids, relevance_grades, k=10):
    """Compute Discounted Cumulative Gain at rank k.

    Uses the standard (non-exponential) gain formula:
        DCG@k = sum_{i=1}^{k} rel_i / log2(i + 1)

    where rel_i is the relevance grade of the document at rank i (1-indexed),
    and documents not in relevance_grades are assumed to have grade 0.

    Args:
        ranked_doc_ids: list of document IDs in rank order (index 0 = rank 1)
        relevance_grades: dict mapping doc_id (int) to relevance grade (int)
        k: cutoff rank

    Returns:
        DCG@k score (float)
    """
    # TODO: implement
    raise NotImplementedError("DCG@k not implemented")


def ndcg_at_k(ranked_doc_ids, relevance_grades, k=10):
    """Compute Normalized Discounted Cumulative Gain at rank k.

    NDCG@k = DCG@k / IDCG@k

    where IDCG@k is the maximum achievable DCG@k (the DCG of the ideal
    ranking, with documents sorted by relevance grade descending).

    Returns 0.0 if no documents in relevance_grades have positive grades
    (i.e., IDCG is 0).

    Args:
        ranked_doc_ids: list of document IDs in rank order
        relevance_grades: dict mapping doc_id (int) to relevance grade (int)
        k: cutoff rank

    Returns:
        NDCG@k score in [0.0, 1.0]
    """
    # TODO: implement
    raise NotImplementedError("NDCG@k not implemented")
