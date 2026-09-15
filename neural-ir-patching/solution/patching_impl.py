
"""Activation patching metrics for neural IR analysis."""


def linear_rank_function(patch_score, clean_score, corrupted_score):
    """Compute the causal effect of patching a model component.

    Returns (patch_score - clean_score) / (corrupted_score - clean_score).
    Supports scalars, lists, and nested lists.
    """
    if isinstance(patch_score, (list, tuple)):
        return [
            linear_rank_function(ps, clean_score, corrupted_score) for ps in patch_score
        ]
    return (patch_score - clean_score) / (corrupted_score - clean_score)


def compute_patching_effects(patching_scores, clean_score, corrupted_score):
    """Apply linear_rank_function element-wise to a nested list of scores."""
    return linear_rank_function(patching_scores, clean_score, corrupted_score)


def _flatten_with_indices(data, prefix=()):
    """Recursively flatten a nested list, yielding (index_tuple, value)."""
    if isinstance(data, (list, tuple)):
        for i, item in enumerate(data):
            yield from _flatten_with_indices(item, prefix + (i,))
    else:
        yield prefix, data


def identify_top_k_critical(effects, k=5):
    """Find the k indices with smallest absolute effect value.

    Args:
        effects: Nested list of effect values (any dimensionality).
        k: Number of top critical components to return.

    Returns:
        List of tuples, sorted by ascending absolute effect value.
    """
    indexed = [(abs(val), idx) for idx, val in _flatten_with_indices(effects)]
    indexed.sort(key=lambda x: x[0])
    return [idx for _, idx in indexed[:k]]
