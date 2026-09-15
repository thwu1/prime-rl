"""Score fusion methods for combining multiple retrieval runs."""


def reciprocal_rank_fusion(runs, k=60):
    """Combine runs using Reciprocal Rank Fusion.

    RRF score for document d = sum over runs of 1/(k + rank(d))
    where rank(d) is the 1-indexed position after sorting by score descending.

    Args:
        runs: list of dicts, each {query_id: {doc_id: score}}
        k: RRF constant (default 60)

    Returns:
        {query_id: {doc_id: fused_score}}
    """
    raise NotImplementedError("RRF fusion not yet implemented")


def normalize_scores(run):
    """Min-max normalize scores per query to [0, 1].

    Args:
        run: {qid: {docid: score}}

    Returns:
        {qid: {docid: normalized_score}}
    """
    raise NotImplementedError("Score normalization not yet implemented")


def comb_sum(runs):
    """Combine runs using CombSUM with min-max normalized scores.

    Normalize each run's scores per query to [0,1], then sum across runs.

    Args:
        runs: list of {qid: {docid: score}}

    Returns:
        {qid: {docid: fused_score}}
    """
    raise NotImplementedError("CombSUM not yet implemented")


def comb_mnz(runs):
    """Combine runs using CombMNZ with min-max normalized scores.

    CombMNZ = CombSUM_score * (number of runs containing the document).

    Args:
        runs: list of {qid: {docid: score}}

    Returns:
        {qid: {docid: fused_score}}
    """
    raise NotImplementedError("CombMNZ not yet implemented")


def weighted_comb_sum(runs, model_weights):
    """Combine runs using Weighted CombSUM.

    Min-max normalize each run per query, then weight model m's normalized
    scores by model_weights[m] before summing. Weights are typically the
    model's baseline nDCG@10 on the target domain.

    Args:
        runs: list of {qid: {docid: score}}
        model_weights: list of floats, one per run

    Returns:
        {qid: {docid: fused_score}}
    """
    raise NotImplementedError("Weighted CombSUM not yet implemented")
