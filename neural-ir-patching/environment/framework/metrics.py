"""Standard IR evaluation metrics for ranking quality assessment.

Provides NDCG@k, AP@k, and Reciprocal Rank computed from predicted
relevance scores and ground-truth labels.

See /app/README.md and /app/specs.md for formula definitions and usage.
"""

import math


class RankingMetrics:
    """Compute standard ranking evaluation metrics."""

    @staticmethod
    def ndcg_at_k(predictions, labels, k):
        """Compute NDCG@k.

        Sort documents by predicted scores (descending), compute DCG@k / IDCG@k.
        Uses gain = 2^rel - 1 and discount = 1/log2(rank+1).

        Args:
            predictions: List of predicted relevance scores.
            labels: List of ground-truth relevance grades (non-negative integers).
            k: Cutoff rank.

        Returns:
            NDCG@k value in [0, 1]. Returns 0.0 if IDCG@k is 0.
        """
        raise NotImplementedError("ndcg_at_k not implemented")

    @staticmethod
    def average_precision_at_k(predictions, labels, k):
        """Compute Average Precision at rank cutoff k.

        Sort documents by predicted scores (descending). At each rank i <= k
        where the document is relevant (label > 0), accumulate precision@i.
        Normalize by min(R, k) where R is total number of relevant documents.

        Args:
            predictions: List of predicted relevance scores.
            labels: List of ground-truth relevance grades.
            k: Cutoff rank.

        Returns:
            AP@k value. Returns 0.0 if no relevant documents exist.
        """
        raise NotImplementedError("average_precision_at_k not implemented")

    @staticmethod
    def reciprocal_rank(predictions, labels):
        """Compute Reciprocal Rank.

        Sort documents by predicted scores (descending). Find the rank of
        the first relevant document (label > 0). Return 1/rank.

        Args:
            predictions: List of predicted relevance scores.
            labels: List of ground-truth relevance grades.

        Returns:
            Reciprocal rank value. Returns 0.0 if no relevant documents.
        """
        raise NotImplementedError("reciprocal_rank not implemented")

    @staticmethod
    def evaluate_queries(ranking_data, k=5):
        """Compute mean NDCG@k, MAP@k, and MRR across all queries.

        Args:
            ranking_data: List of dicts, each with 'predictions' and 'labels'.
            k: Cutoff rank for NDCG and MAP.

        Returns:
            Dict with keys 'ndcg', 'map', 'mrr' containing mean metric values.
        """
        raise NotImplementedError("evaluate_queries not implemented")
