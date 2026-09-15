"""Bin edge computation for PLE encoding."""

import numpy as np


def compute_bins(X, n_bins=48, *, y=None, regression=None, tree_kwargs=None):
    """Compute bin edges for each feature column of X.

    Quantile mode (tree_kwargs is None): equally-spaced quantile edges.
    Tree mode (tree_kwargs provided): decision-tree-based split thresholds.
    """
    if not np.all(np.isfinite(X)):
        raise ValueError("X contains non-finite values")
    if X.shape[0] < 2:
        raise ValueError("Need at least 2 rows")
    if n_bins <= 1 or n_bins >= len(X):
        raise ValueError(f"n_bins must satisfy 1 < n_bins < {len(X)}")
    for col in range(X.shape[1]):
        if X[:, col].min() == X[:, col].max():
            raise ValueError(f"Column {col} is constant")

    if tree_kwargs is None:
        if y is not None or regression is not None:
            raise ValueError("y/regression must be None in quantile mode")
        return _quantile_bins(X, n_bins)
    else:
        if y is None:
            raise ValueError("y is required for tree mode")
        if regression is None:
            raise ValueError("regression flag is required for tree mode")
        if 'max_leaf_nodes' in tree_kwargs:
            raise ValueError("max_leaf_nodes should not be in tree_kwargs")
        return _tree_bins(X, n_bins, y, regression, tree_kwargs)


def _quantile_bins(X, n_bins):
    bins = []
    for col in range(X.shape[1]):
        q = np.linspace(0.0, 1.0, n_bins + 1)
        edges = np.quantile(X[:, col], q)
        edges = np.unique(edges)
        bins.append(edges)
    return bins


def _tree_bins(X, n_bins, y, regression, tree_kwargs):
    from sklearn.tree import DecisionTreeRegressor, DecisionTreeClassifier

    bins = []
    for col in range(X.shape[1]):
        TreeCls = DecisionTreeRegressor if regression else DecisionTreeClassifier
        tree = TreeCls(max_leaf_nodes=n_bins, **tree_kwargs)
        tree.fit(X[:, col:col + 1], y)

        thresholds = set()
        for node_id in range(tree.tree_.node_count):
            left = tree.tree_.children_left[node_id]
            right = tree.tree_.children_right[node_id]
            if left != right:
                thresholds.add(float(tree.tree_.threshold[node_id]))

        edges = np.array(sorted(thresholds))
        bins.append(edges)
    return bins
