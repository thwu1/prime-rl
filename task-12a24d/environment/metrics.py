"""Retrieval evaluation metrics using pytrec_eval.

Reference implementation from the BRIGHT benchmark (xlang-ai/BRIGHT).
Install pytrec-eval-terrier to use: pip3 install pytrec-eval-terrier
"""

import pytrec_eval


def calculate_retrieval_metrics(results, qrels, k_values=[1, 5, 10, 25, 50, 100]):
    """Compute retrieval metrics (nDCG, MAP, Recall, Precision, MRR).

    Args:
        results: {query_id: {doc_id: float_score, ...}, ...}
        qrels:   {query_id: {doc_id: int_relevance, ...}, ...}
        k_values: cutoff values for metrics

    Returns:
        dict with metric names as keys and averaged scores as values
    """
    ndcg = {}
    _map = {}
    recall = {}
    precision = {}
    mrr = {"MRR": 0}

    for k in k_values:
        ndcg[f"NDCG@{k}"] = 0.0
        _map[f"MAP@{k}"] = 0.0
        recall[f"Recall@{k}"] = 0.0
        precision[f"P@{k}"] = 0.0

    map_string = "map_cut." + ",".join([str(k) for k in k_values])
    ndcg_string = "ndcg_cut." + ",".join([str(k) for k in k_values])
    recall_string = "recall." + ",".join([str(k) for k in k_values])
    precision_string = "P." + ",".join([str(k) for k in k_values])

    evaluator = pytrec_eval.RelevanceEvaluator(
        qrels,
        {map_string, ndcg_string, recall_string, precision_string, "recip_rank"},
    )
    scores = evaluator.evaluate(results)

    for query_id in scores.keys():
        for k in k_values:
            ndcg[f"NDCG@{k}"] += scores[query_id]["ndcg_cut_" + str(k)]
            _map[f"MAP@{k}"] += scores[query_id]["map_cut_" + str(k)]
            recall[f"Recall@{k}"] += scores[query_id]["recall_" + str(k)]
            precision[f"P@{k}"] += scores[query_id]["P_" + str(k)]
        mrr["MRR"] += scores[query_id]["recip_rank"]

    for k in k_values:
        ndcg[f"NDCG@{k}"] = round(ndcg[f"NDCG@{k}"] / len(scores), 5)
        _map[f"MAP@{k}"] = round(_map[f"MAP@{k}"] / len(scores), 5)
        recall[f"Recall@{k}"] = round(recall[f"Recall@{k}"] / len(scores), 5)
        precision[f"P@{k}"] = round(precision[f"P@{k}"] / len(scores), 5)
    mrr["MRR"] = round(mrr["MRR"] / len(scores), 5)

    output = {**ndcg, **_map, **recall, **precision, **mrr}
    return output
