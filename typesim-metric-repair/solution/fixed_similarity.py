"""Type similarity computation — complete implementation.

Implements the TypeSim metric with:
- Base constructor scoring (1.0/0.5/0.0)
- Positional argument comparison with arithmetic mean integration
- Hungarian algorithm for optimal union member matching
"""

import numpy as np
from scipy.optimize import linear_sum_assignment

from typesim.parser import TypeNode


def base_type_similarity(a: TypeNode, b: TypeNode) -> float:
    """Compute similarity between base type constructor names.

    Returns:
        1.0 if same type name
        0.5 if either type is Any
        0.0 otherwise
    """
    if a.name == b.name:
        return 1.0
    if a.name == "Any" or b.name == "Any":
        return 0.5
    return 0.0


def type_similarity(a: TypeNode, b: TypeNode) -> float:
    """Compute TypeSim similarity score between two type nodes.

    Returns a float in [0.0, 1.0] where 1.0 means identical types.
    """
    # Fast path: exact string match
    if str(a) == str(b):
        return 1.0

    # Union type handling
    if a.name == "Union" and b.name == "Union":
        return _union_similarity(a.args, b.args)
    if a.name == "Union":
        return _union_similarity(a.args, [b])
    if b.name == "Union":
        return _union_similarity([a], b.args)

    # Non-union similarity
    base_score = base_type_similarity(a, b)

    a_has_args = len(a.args) > 0
    b_has_args = len(b.args) > 0

    if a_has_args and b_has_args:
        min_len = min(len(a.args), len(b.args))
        max_len = max(len(a.args), len(b.args))
        total = sum(
            type_similarity(a.args[i], b.args[i]) for i in range(min_len)
        )
        arg_avg = total / max_len
        score = (base_score + arg_avg) / 2
    elif a_has_args or b_has_args:
        score = base_score / 2
    else:
        score = base_score

    return score


def _union_similarity(a_items: list, b_items: list) -> float:
    """Compute similarity between union type members using Hungarian algorithm.

    Builds a cost matrix of pairwise type similarities, then finds the
    optimal assignment maximizing total similarity.
    """
    n = len(a_items)
    m = len(b_items)

    # Build cost matrix
    cost = np.zeros((n, m))
    for i in range(n):
        for j in range(m):
            cost[i, j] = type_similarity(a_items[i], b_items[j])

    # Find optimal assignment (maximize similarity via negation)
    row_ind, col_ind = linear_sum_assignment(-cost)
    matched_sum = cost[row_ind, col_ind].sum()

    return float(matched_sum / max(n, m))
