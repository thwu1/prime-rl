#!/usr/bin/env python3
"""
Portfolio allocation tool — draft implementation.
Uses hierarchical clustering with risk-based weight allocation
and optional covariance denoising.
"""

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster, to_tree
from scipy.spatial.distance import squareform
import json
import argparse
import math


# ---------------------------------------------------------------------------
# Covariance denoising
# ---------------------------------------------------------------------------

def denoise_covariance(cov, tn_ratio, kde_bwidth=0.25):
    """Denoise an empirical covariance matrix using eigenvalue methods.

    Parameters
    ----------
    cov : np.ndarray
        N x N empirical covariance matrix.
    tn_ratio : float
        T / N (number of observations / number of variables).
    kde_bwidth : float
        KDE bandwidth for eigenvalue density estimation.

    Returns
    -------
    np.ndarray
        Denoised covariance matrix.
    """
    N = cov.shape[0]

    # Convert covariance to correlation
    std = np.sqrt(np.diag(cov))
    corr = cov / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)

    # Eigendecomposition
    eigenvalues, eigenvectors = np.linalg.eigh(corr)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx].copy()
    eigenvectors = eigenvectors[:, idx].copy()

    # Determine noise threshold from theoretical distribution
    # For a correlation matrix, assume noise variance sigma^2 = 1
    q = tn_ratio
    sigma2 = 1.0
    lam_max = sigma2 * (1.0 + 1.0 / math.sqrt(q)) ** 2

    # Replace noise eigenvalues with their mean (constant residual)
    noise_mask = eigenvalues <= lam_max
    if noise_mask.any() and not noise_mask.all():
        eigenvalues[noise_mask] = eigenvalues[noise_mask].mean()

    # Reconstruct correlation matrix
    corr_den = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T

    # Rescale to unit diagonal
    d = np.sqrt(np.diag(corr_den))
    corr_den = corr_den / np.outer(d, d)
    corr_den = (corr_den + corr_den.T) / 2.0
    np.fill_diagonal(corr_den, 1.0)

    # Convert back to covariance
    cov_den = corr_den * np.outer(std, std)
    return cov_den


# ---------------------------------------------------------------------------
# Risk measures
# ---------------------------------------------------------------------------

def compute_cvar(returns, alpha=0.05):
    """Compute Conditional Value-at-Risk.

    Sorts returns and takes the average of the worst tail observations.
    """
    sorted_ret = np.sort(returns)
    n = len(sorted_ret)
    cutoff = max(int(math.floor(n * alpha)), 1)
    return float(np.mean(sorted_ret[:cutoff]))


def _compute_risk(returns, risk_measure='cvar', alpha=0.05):
    """Compute risk for a single return series."""
    if risk_measure == 'variance':
        return float(np.var(returns, ddof=1))
    elif risk_measure == 'std':
        return float(np.std(returns, ddof=1))
    elif risk_measure == 'cvar':
        return compute_cvar(returns, alpha)
    else:
        raise ValueError(f"Unknown risk measure: {risk_measure}")


# ---------------------------------------------------------------------------
# Cluster count selection
# ---------------------------------------------------------------------------

def _find_n_clusters(Z, N):
    """Determine optimal number of clusters from linkage matrix.

    Uses the largest gap in merge distances as a heuristic.
    """
    merge_dists = Z[:, 2]
    gaps = np.diff(merge_dists)
    if len(gaps) > 1:
        n_clusters = len(gaps) - np.argmax(gaps)
        n_clusters = max(2, min(n_clusters, N - 1))
    else:
        n_clusters = 2
    return n_clusters


# ---------------------------------------------------------------------------
# Portfolio allocation
# ---------------------------------------------------------------------------

def _get_leaves(node):
    """Return sorted list of leaf IDs under a ClusterNode."""
    if node.is_leaf():
        return [node.id]
    return _get_leaves(node.get_left()) + _get_leaves(node.get_right())


def herc_allocate(returns, risk_measure='cvar', linkage_method='ward',
                  cvar_alpha=0.05, denoise=False, kde_bwidth=0.25):
    """Hierarchical allocation with optional covariance denoising.

    Parameters
    ----------
    returns : pd.DataFrame
        Daily log returns (rows = dates, columns = asset tickers).
    risk_measure : str
        One of 'cvar', 'variance', 'std'.
    linkage_method : str
        One of 'ward', 'single', 'complete', 'average'.
    cvar_alpha : float
        Tail probability for CVaR.
    denoise : bool
        Whether to apply covariance denoising.
    kde_bwidth : float
        KDE bandwidth for denoising.

    Returns
    -------
    dict
        {'weights': {ticker: float}, 'n_clusters': int, 'denoised': bool}
    """
    assets = list(returns.columns)
    N = len(assets)
    T = len(returns)

    # Covariance estimation (optionally denoised)
    cov = returns.cov().values
    if denoise:
        cov = denoise_covariance(cov, T / N, kde_bwidth)

    # Build correlation-based distance matrix
    std = np.sqrt(np.diag(cov))
    corr = cov / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)

    dist = np.sqrt(0.5 * (1.0 - corr))
    np.fill_diagonal(dist, 0.0)

    # Hierarchical clustering
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method=linkage_method)

    # Determine cluster count
    n_clusters = _find_n_clusters(Z, N)
    cluster_labels = fcluster(Z, n_clusters, criterion='maxclust')

    # Per-asset risk
    asset_risks = np.array([
        _compute_risk(returns.iloc[:, i].values, risk_measure, cvar_alpha)
        for i in range(N)
    ])
    asset_risks = np.maximum(asset_risks, 1e-20)

    # Build dendrogram tree
    root = to_tree(Z)

    # Top-down recursive bisection to cluster level
    cluster_weights = {}

    def _bisect(node, w):
        items = _get_leaves(node)
        cset = set(cluster_labels[i] for i in items)

        if len(cset) == 1:
            cid = cset.pop()
            cluster_weights[cid] = cluster_weights.get(cid, 0.0) + w
            return

        if node.is_leaf():
            cid = cluster_labels[node.id]
            cluster_weights[cid] = cluster_weights.get(cid, 0.0) + w
            return

        left_items = _get_leaves(node.get_left())
        right_items = _get_leaves(node.get_right())

        left_risk = sum(asset_risks[i] for i in left_items)
        right_risk = sum(asset_risks[i] for i in right_items)
        total = left_risk + right_risk

        if total < 1e-30:
            a = 0.5
        else:
            # Allocate proportional to risk contribution
            a = left_risk / total

        _bisect(node.get_left(), w * a)
        _bisect(node.get_right(), w * (1.0 - a))

    _bisect(root, 1.0)

    # Within-cluster allocation: inverse-risk weighting
    final_w = np.zeros(N)
    for cid, cw in cluster_weights.items():
        members = [i for i in range(N) if cluster_labels[i] == cid]
        inv = np.array([1.0 / asset_risks[i] for i in members])
        inv_total = inv.sum()
        for idx_m, m in enumerate(members):
            final_w[m] = cw * inv[idx_m] / inv_total

    # Normalise
    s = final_w.sum()
    if s > 0:
        final_w /= s

    return {
        'weights': {assets[i]: float(final_w[i]) for i in range(N)},
        'n_clusters': int(n_clusters),
        'denoised': bool(denoise),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Portfolio Allocation Tool')
    parser.add_argument('--input', required=True, help='Input CSV path')
    parser.add_argument('--output', required=True, help='Output JSON path')
    parser.add_argument('--risk-measure', default='cvar',
                        choices=['cvar', 'variance', 'std'])
    parser.add_argument('--linkage', default='ward',
                        choices=['ward', 'single', 'complete', 'average'])
    parser.add_argument('--cvar-alpha', type=float, default=0.05)
    parser.add_argument('--denoise', action='store_true')
    parser.add_argument('--kde-bwidth', type=float, default=0.25)
    args = parser.parse_args()

    returns = pd.read_csv(args.input, index_col=0, parse_dates=True)

    result = herc_allocate(
        returns,
        risk_measure=args.risk_measure,
        linkage_method=args.linkage,
        cvar_alpha=args.cvar_alpha,
        denoise=args.denoise,
        kde_bwidth=args.kde_bwidth,
    )

    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)


if __name__ == '__main__':
    main()
