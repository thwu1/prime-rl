"""Piecewise Linear Encoding library for tabular data.

"""
import numpy as np


def compute_bins(X, n_bins=48, *, y=None, regression=None, tree_kwargs=None):
    """Compute bin edges for piecewise-linear encoding.

    Quantile mode (tree_kwargs is None): compute equally-spaced quantile
    points per feature, then deduplicate.

    Tree mode (tree_kwargs provided): fit a decision tree per feature and
    extract split thresholds combined with feature min/max.
    """
    if not isinstance(X, np.ndarray):
        raise ValueError("X must be a numpy array")
    if X.ndim != 2:
        raise ValueError("X must be 2-dimensional")
    if X.shape[0] < 2:
        raise ValueError("X must have at least 2 rows")
    if X.shape[1] < 1:
        raise ValueError("X must have at least 1 column")
    if not np.isfinite(X).all():
        raise ValueError("X must not contain nan/inf/-inf")
    if np.any(np.all(X == X[0:1, :], axis=0)):
        raise ValueError("X contains constant columns")
    if n_bins <= 1 or n_bins >= len(X):
        raise ValueError(
            f"n_bins must be > 1 and < len(X), got n_bins={n_bins}, len(X)={len(X)}"
        )

    if tree_kwargs is None:
        if y is not None or regression is not None:
            raise ValueError(
                "If tree_kwargs is None, y and regression must also be None"
            )
        quantile_points = np.linspace(0.0, 1.0, n_bins + 1)
        bins = []
        for col_idx in range(X.shape[1]):
            q = np.quantile(X[:, col_idx], quantile_points)
            bins.append(np.unique(q))
        return bins
    else:
        if y is None or regression is None:
            raise ValueError(
                "If tree_kwargs is not None, y and regression must not be None"
            )
        if "max_leaf_nodes" in tree_kwargs:
            raise ValueError(
                "tree_kwargs must not contain 'max_leaf_nodes' "
                "(it is set automatically to n_bins)"
            )
        from sklearn.tree import DecisionTreeRegressor, DecisionTreeClassifier

        bins = []
        for col_idx in range(X.shape[1]):
            column = X[:, col_idx]
            feature_bin_edges = [float(column.min()), float(column.max())]
            TreeClass = (
                DecisionTreeRegressor if regression else DecisionTreeClassifier
            )
            tree = (
                TreeClass(max_leaf_nodes=n_bins, **tree_kwargs)
                .fit(column.reshape(-1, 1), y)
                .tree_
            )
            for node_id in range(tree.node_count):
                if tree.children_left[node_id] != tree.children_right[node_id]:
                    feature_bin_edges.append(float(tree.threshold[node_id]))
            bins.append(np.unique(np.array(feature_bin_edges)))
        return bins


class PiecewiseLinearEncoder:
    """Piecewise-linear encoder for tabular features.

    Encodes each feature using a piecewise-linear scheme defined by bin edges.
    The encoding layout places the last bin component at position max_n_bins-1,
    with leading components at positions 0..k-2 and zero-padding in between.
    """

    def __init__(self, bins):
        if not bins:
            raise ValueError("bins must not be empty")
        for i, b in enumerate(bins):
            if not isinstance(b, np.ndarray):
                raise ValueError(f"bins[{i}] must be a numpy array")
            if b.ndim != 1:
                raise ValueError(f"bins[{i}] must be 1-dimensional")
            if len(b) < 2:
                raise ValueError(f"bins[{i}] must have at least 2 edges")

        self._bins = [b.astype(np.float64) for b in bins]
        self._n_features = len(bins)
        self._n_bins_per_feature = [len(b) - 1 for b in bins]
        self._max_n_bins = max(self._n_bins_per_feature)
        self._total_n_bins = sum(self._n_bins_per_feature)

        self._single_bin_mask = np.array(self._n_bins_per_feature) == 1

        # Build weight and bias for the linear transform representation
        self._weight = np.zeros(
            (self._n_features, self._max_n_bins), dtype=np.float64
        )
        self._bias = np.zeros(
            (self._n_features, self._max_n_bins), dtype=np.float64
        )

        # Build validity mask for flat output
        all_same = all(
            nb == self._n_bins_per_feature[0]
            for nb in self._n_bins_per_feature
        )
        if all_same:
            self._mask = None
        else:
            masks = []
            for nb in self._n_bins_per_feature:
                m = np.concatenate([
                    np.ones(nb - 1, dtype=bool),
                    np.zeros(self._max_n_bins - nb, dtype=bool),
                    np.ones(1, dtype=bool),
                ])
                masks.append(m)
            self._mask = np.stack(masks)

        # Fill weight and bias from bin edges
        for i, edges in enumerate(self._bins):
            widths = np.diff(edges)
            w = 1.0 / widths
            b = -edges[:-1] / widths
            nb = self._n_bins_per_feature[i]
            # Last component always at position max_n_bins - 1
            self._weight[i, -1] = w[-1]
            self._bias[i, -1] = b[-1]
            # Leading components at positions 0..nb-2
            if nb > 1:
                self._weight[i, : nb - 1] = w[:-1]
                self._bias[i, : nb - 1] = b[:-1]

    @property
    def n_features(self):
        return self._n_features

    @property
    def max_n_bins(self):
        return self._max_n_bins

    @property
    def total_n_bins(self):
        return self._total_n_bins

    def encode_structured(self, X):
        """Encode features into the structured layout.

        Returns shape (batch, n_features, max_n_bins).
        """
        if X.ndim != 2:
            raise ValueError("X must be 2-dimensional")
        if X.shape[1] != self._n_features:
            raise ValueError(
                f"Expected {self._n_features} features, got {X.shape[1]}"
            )

        X = X.astype(np.float64)
        # Linear transform: out[i, j, k] = weight[j, k] * X[i, j] + bias[j, k]
        out = (
            self._weight[np.newaxis, :, :] * X[:, :, np.newaxis]
            + self._bias[np.newaxis, :, :]
        )

        if self._max_n_bins > 1:
            # Position 0: upper-bounded at 1
            first = np.minimum(out[:, :, :1], 1.0)
            # Positions 1..max_n_bins-2: clamped to [0, 1]
            middle = np.clip(out[:, :, 1:-1], 0.0, 1.0)
            # Position max_n_bins-1: lower-bounded at 0 (except single-bin)
            last = out[:, :, -1:]
            if self._single_bin_mask.any():
                last = np.where(
                    self._single_bin_mask[np.newaxis, :, np.newaxis],
                    last,
                    np.maximum(last, 0.0),
                )
            else:
                last = np.maximum(last, 0.0)
            out = np.concatenate([first, middle, last], axis=-1)
        # If max_n_bins == 1: all features have 1 bin, no clamping

        return out

    def encode_flat(self, X):
        """Encode features into the flat layout (padding removed).

        Returns shape (batch, total_n_bins).
        """
        structured = self.encode_structured(X)
        if self._mask is None:
            return structured.reshape(X.shape[0], -1)
        else:
            return structured[:, self._mask]
