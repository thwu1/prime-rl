#!/usr/bin/env python3
"""Write the typesim similarity module."""

content = r'''"""Type similarity scoring using structural attribute comparison and Hungarian matching."""

from collections import deque

import numpy as np
from scipy.optimize import linear_sum_assignment


# Build attribute sets from actual Python runtime objects
_ATTR_SETS = {
    "int": set(dir(int)),
    "str": set(dir(str)),
    "float": set(dir(float)),
    "bool": set(dir(bool)),
    "list": set(dir(list)),
    "dict": set(dir(dict)),
    "tuple": set(dir(tuple)),
    "set": set(dir(set)),
    "frozenset": set(dir(frozenset)),
    "bytes": set(dir(bytes)),
    "None": set(dir(None)),
    "Any": set(dir(object)),
    "Callable": set(dir(lambda: None)),
    "object": set(dir(object)),
    "deque": set(dir(deque)),
}

UNIVERSAL = set(dir(object))


def _get_attrs(name):
    """Get the attribute set for a base type name."""
    return _ATTR_SETS.get(name, UNIVERSAL)


def _base_similarity(a_name, b_name):
    """Compute Jaccard-like attribute similarity between two base types."""
    a_attrs = _get_attrs(a_name)
    b_attrs = _get_attrs(b_name)
    sym_diff = a_attrs.symmetric_difference(b_attrs)
    common = a_attrs.intersection(b_attrs)
    common_non_universal = common - UNIVERSAL
    numerator = len(sym_diff)
    denominator = len(common_non_universal) + len(sym_diff)
    if denominator == 0 and numerator == 0:
        return 1.0
    return 1.0 - numerator / denominator


def _compare_union(a_list, b_list):
    """Compare two lists of types using Hungarian matching to maximize similarity."""
    cost = np.zeros((len(b_list), len(a_list)))
    for i in range(len(b_list)):
        for j in range(len(a_list)):
            cost[i, j] = get_type_similarity(b_list[i], a_list[j])
    row_ind, col_ind = linear_sum_assignment(-cost)
    total = cost[row_ind, col_ind].sum()
    return total / max(len(a_list), len(b_list))


def get_type_similarity(a, b):
    """Compute the structural similarity between two TypeNode instances.

    Args:
        a: A TypeNode (from typesim.parser.parse_type)
        b: A TypeNode

    Returns:
        A float in [0.0, 1.0] representing type similarity.
    """
    # Handle union cases
    if a.is_union and not b.is_union:
        return _compare_union(a.args, [b])
    if not a.is_union and b.is_union:
        return _compare_union([a], b.args)
    if a.is_union and b.is_union:
        return _compare_union(a.args, b.args)

    # Identical check (same name, recursively same args)
    if a.name == b.name and len(a.args) == len(b.args) and len(a.args) == 0:
        return 1.0
    if a.name == b.name and len(a.args) == len(b.args) and len(a.args) > 0:
        all_same = all(
            get_type_similarity(aa, bb) == 1.0
            for aa, bb in zip(a.args, b.args)
        )
        if all_same:
            return 1.0

    # Compute base similarity
    score = _base_similarity(a.name, b.name)

    # Filter out ellipsis markers from args for comparison
    a_args = [x for x in a.args if x.name != "..."]
    b_args = [x for x in b.args if x.name != "..."]

    if a_args and b_args:
        # Both have type arguments — compare positionally
        arg_score = 0.0
        for i in range(min(len(a_args), len(b_args))):
            arg_score += get_type_similarity(a_args[i], b_args[i])
        arg_score /= max(len(a_args), len(b_args))
        score = (score + arg_score) / 2
    elif a_args or b_args:
        # Only one side has arguments
        score /= 2

    return score
'''

with open("/app/typesim/similarity.py", "w") as f:
    f.write(content)
