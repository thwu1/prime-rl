"""Rank fusion methods for combining multiple retrieval runs.

Each fusion function takes a dict of runs:
    runs: dict mapping run_name (str) -> {qid (int): [pid1, pid2, ...]}
and returns a single fused run:
    {qid (int): [pid1, pid2, ...]}

Passages are ordered by fused score descending; ties broken by
ascending passage ID.
"""

from collections import defaultdict


def rrf_fusion(runs, k_param=60):
    """Reciprocal Rank Fusion (Cormack et al., 2009).

    For each query-document pair, compute:
        score(d) = sum_{r in runs} 1 / (k_param + rank_r(d))

    where rank_r(d) is the 1-based rank of document d in run r.
    Re-rank by score descending, breaking ties by ascending passage ID.

    Args:
        runs: dict of run_name -> run_dict
        k_param: RRF smoothing constant (default 60)

    Returns:
        Fused run dict: qid -> [pid, ...]
    """
    raise NotImplementedError("RRF fusion not yet implemented")


def combsum_fusion(runs):
    """CombSUM fusion using min-max normalized rank-based scores.

    For each run, compute a normalized score per document:
        score = 1 - (rank - 1) / max_rank
    where max_rank is the number of documents in that run for that query.

    Sum the normalized scores across all runs.
    Re-rank by score descending, breaking ties by ascending passage ID.

    Args:
        runs: dict of run_name -> run_dict

    Returns:
        Fused run dict: qid -> [pid, ...]
    """
    raise NotImplementedError("CombSUM fusion not yet implemented")
