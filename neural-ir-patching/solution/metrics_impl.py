
"""Standard IR evaluation metrics for ranking quality assessment."""

import math


class RankingMetrics:
    """Compute standard ranking evaluation metrics."""

    @staticmethod
    def ndcg_at_k(predictions, labels, k):
        """Compute NDCG@k."""
        n = len(predictions)
        sorted_indices = sorted(range(n), key=lambda i: predictions[i], reverse=True)
        sorted_labels = [labels[i] for i in sorted_indices]

        dcg = 0.0
        for i in range(min(k, n)):
            dcg += (2 ** sorted_labels[i] - 1) / math.log2(i + 2)

        ideal_labels = sorted(labels, reverse=True)
        idcg = 0.0
        for i in range(min(k, n)):
            idcg += (2 ** ideal_labels[i] - 1) / math.log2(i + 2)

        if idcg == 0:
            return 0.0
        return dcg / idcg

    @staticmethod
    def average_precision_at_k(predictions, labels, k):
        """Compute AP@k."""
        n = len(predictions)
        sorted_indices = sorted(range(n), key=lambda i: predictions[i], reverse=True)
        sorted_labels = [labels[i] for i in sorted_indices]

        total_relevant = sum(1 for l in labels if l > 0)
        if total_relevant == 0:
            return 0.0

        num_relevant = 0
        sum_precision = 0.0
        for i in range(min(k, n)):
            if sorted_labels[i] > 0:
                num_relevant += 1
                sum_precision += num_relevant / (i + 1)

        return sum_precision / min(total_relevant, k)

    @staticmethod
    def reciprocal_rank(predictions, labels):
        """Compute Reciprocal Rank."""
        n = len(predictions)
        sorted_indices = sorted(range(n), key=lambda i: predictions[i], reverse=True)
        sorted_labels = [labels[i] for i in sorted_indices]

        for i, label in enumerate(sorted_labels):
            if label > 0:
                return 1.0 / (i + 1)
        return 0.0

    @staticmethod
    def evaluate_queries(ranking_data, k=5):
        """Compute mean NDCG@k, MAP@k, and MRR across all queries."""
        ndcg_vals = []
        map_vals = []
        mrr_vals = []

        for query in ranking_data:
            preds = query["predictions"]
            labs = query["labels"]
            ndcg_vals.append(RankingMetrics.ndcg_at_k(preds, labs, k))
            map_vals.append(RankingMetrics.average_precision_at_k(preds, labs, k))
            mrr_vals.append(RankingMetrics.reciprocal_rank(preds, labs))

        return {
            "ndcg": sum(ndcg_vals) / len(ndcg_vals),
            "map": sum(map_vals) / len(map_vals),
            "mrr": sum(mrr_vals) / len(mrr_vals),
        }
