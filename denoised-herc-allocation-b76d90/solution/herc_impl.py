#!/usr/bin/env python3
"""
Denoised HERC Portfolio Allocation System.

Combines Marchenko-Pastur covariance matrix denoising with the Hierarchical
Equal Risk Contribution (HERC) algorithm for robust portfolio allocation.
"""

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster, to_tree
from scipy.optimize import minimize_scalar
from scipy.spatial.distance import squareform, pdist
from scipy.stats import gaussian_kde
import json
import argparse
import math


# ---------------------------------------------------------------------------
# Marchenko-Pastur denoising
# ---------------------------------------------------------------------------

def _mp_pdf(x, sigma2, q):
    """Marchenko-Pastur probability density function."""
    sqrt_q = math.sqrt(q)
    lam_min = sigma2 * (1.0 - 1.0 / sqrt_q) ** 2
    lam_max = sigma2 * (1.0 + 1.0 / sqrt_q) ** 2
    pdf = np.zeros_like(x, dtype=float)
    mask = (x >= lam_min) & (x <= lam_max)
    if mask.any():
        xm = x[mask]
        pdf[mask] = (q / (2.0 * np.pi * sigma2)) * \
            np.sqrt(np.maximum((lam_max - xm) * (xm - lam_min), 0.0)) / xm
    return pdf


def _fit_mp_variance(eigenvalues, q, kde_bwidth=0.25):
    """Fit MP distribution to eigenvalue density and return (sigma2, lambda_max).

    For a correlation matrix the trace = N so the average eigenvalue = 1.
    The noise variance sigma2 should be at most 1 (pure noise) and in
    practice less (signal steals some variance).  We bound the search
    accordingly to avoid the optimizer locking on to signal eigenvalues.
    """
    kde = gaussian_kde(eigenvalues, bw_method=kde_bwidth)

    # Evaluate KDE on a grid covering the plausible noise range.
    # We extend a little above the MP upper edge for sigma2=1.
    sqrt_q = math.sqrt(q)
    upper_for_unit = (1.0 + 1.0 / sqrt_q) ** 2  # lambda_max when sigma2=1
    x_lo = max(eigenvalues.min() * 0.5, 1e-10)
    x_hi = max(upper_for_unit * 1.5, eigenvalues.max() * 0.5)
    x = np.linspace(x_lo, x_hi, 1000)
    kde_vals = kde(x)

    def err(sigma2):
        mp = _mp_pdf(x, sigma2, q)
        return float(np.sum((kde_vals - mp) ** 2))

    # sigma2 bounded to (0, 1] for a correlation matrix
    res = minimize_scalar(err, bounds=(1e-5, 1.0), method='bounded')
    sigma2 = res.x
    lam_max = sigma2 * (1.0 + 1.0 / sqrt_q) ** 2
    return sigma2, lam_max


def denoise_covariance(cov, tn_ratio, kde_bwidth=0.25):
    """Denoise a covariance matrix via Marchenko-Pastur constant residual
    eigenvalue method.

    Parameters
    ----------
    cov : np.ndarray
        N x N empirical covariance matrix.
    tn_ratio : float
        T / N (observations / variables).
    kde_bwidth : float
        KDE bandwidth for eigenvalue density.

    Returns
    -------
    np.ndarray
        Denoised covariance matrix (PSD, symmetric).
    """
    N = cov.shape[0]

    # Covariance -> correlation
    std = np.sqrt(np.diag(cov))
    corr = cov / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)

    # Eigendecomposition (ascending order from eigh)
    eigenvalues, eigenvectors = np.linalg.eigh(corr)

    # Sort descending
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx].copy()
    eigenvectors = eigenvectors[:, idx].copy()

    # Fit MP and find noise threshold
    _, lam_max = _fit_mp_variance(eigenvalues, tn_ratio, kde_bwidth)

    # Constant residual: replace noise eigenvalues with their mean
    noise_mask = eigenvalues <= lam_max
    if noise_mask.any() and not noise_mask.all():
        eigenvalues[noise_mask] = eigenvalues[noise_mask].mean()

    # Reconstruct correlation
    corr_den = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T

    # Rescale diagonal to 1
    d = np.sqrt(np.diag(corr_den))
    corr_den = corr_den / np.outer(d, d)

    # Force exact symmetry
    corr_den = (corr_den + corr_den.T) / 2.0
    np.fill_diagonal(corr_den, 1.0)

    # Correlation -> covariance
    cov_den = corr_den * np.outer(std, std)
    return cov_den


# ---------------------------------------------------------------------------
# Risk measures
# ---------------------------------------------------------------------------

def compute_cvar(returns, alpha=0.05):
    """Conditional Value-at-Risk (Expected Shortfall).

    Returns the negative mean of the worst ceil(n*alpha) returns,
    i.e. a positive number for typical loss distributions.
    """
    sorted_ret = np.sort(returns)
    n = len(sorted_ret)
    cutoff = int(math.ceil(n * alpha))
    if cutoff < 1:
        cutoff = 1
    return -float(np.mean(sorted_ret[:cutoff]))


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
# Gap statistic
# ---------------------------------------------------------------------------

def _gap_statistic(distance_matrix, Z, B=50, max_clusters=None, seed=42):
    """Gap statistic (Tibshirani et al. 2001) for optimal cluster count."""
    N = distance_matrix.shape[0]
    if max_clusters is None:
        max_clusters = min(N - 1, 15)
    max_clusters = max(max_clusters, 2)
    rng = np.random.RandomState(seed)

    col_min = distance_matrix.min(axis=0)
    col_max = distance_matrix.max(axis=0)

    def _wk(data, labels):
        wk = 0.0
        for k in np.unique(labels):
            pts = data[labels == k]
            nk = len(pts)
            if nk > 1:
                d = pdist(pts)
                wk += np.sum(d ** 2) / (2.0 * nk)
        return max(wk, 1e-300)

    gaps = []
    sks = []

    for k in range(1, max_clusters + 1):
        labels = fcluster(Z, k, criterion='maxclust')
        log_wk = np.log(_wk(distance_matrix, labels))

        ref_logs = []
        for _ in range(B):
            ref = np.column_stack([
                rng.uniform(col_min[c], col_max[c], N) for c in range(N)
            ])
            ref_cd = pdist(ref)
            ref_Z = linkage(ref_cd, method='ward')
            ref_labels = fcluster(ref_Z, k, criterion='maxclust')
            ref_logs.append(np.log(_wk(ref, ref_labels)))

        gap = np.mean(ref_logs) - log_wk
        sdk = np.std(ref_logs, ddof=0)
        sk = sdk * np.sqrt(1.0 + 1.0 / B)
        gaps.append(gap)
        sks.append(sk)

    # Tibshirani rule
    for i in range(len(gaps) - 1):
        if gaps[i] >= gaps[i + 1] - sks[i + 1]:
            return i + 1
    return max_clusters


# ---------------------------------------------------------------------------
# HERC allocation
# ---------------------------------------------------------------------------

def _get_leaves(node):
    """Return sorted list of leaf IDs under a ClusterNode."""
    if node.is_leaf():
        return [node.id]
    return _get_leaves(node.get_left()) + _get_leaves(node.get_right())


def herc_allocate(returns, risk_measure='cvar', linkage_method='ward',
                  cvar_alpha=0.05, denoise=False, kde_bwidth=0.25):
    """Hierarchical Equal Risk Contribution (HERC) portfolio allocation.

    Parameters
    ----------
    returns : pd.DataFrame
        Rows = dates, columns = asset tickers, values = daily log returns.
    risk_measure : str
        One of 'cvar', 'variance', 'std'.
    linkage_method : str
        One of 'ward', 'single', 'complete', 'average'.
    cvar_alpha : float
        Tail probability for CVaR.
    denoise : bool
        Apply Marchenko-Pastur denoising before allocation.
    kde_bwidth : float
        KDE bandwidth for MP fitting.

    Returns
    -------
    dict
        {'weights': {ticker: float}, 'n_clusters': int, 'denoised': bool}
    """
    assets = list(returns.columns)
    N = len(assets)
    T = len(returns)

    # Covariance (optionally denoised)
    cov = returns.cov().values
    if denoise:
        cov = denoise_covariance(cov, T / N, kde_bwidth)

    # Correlation-distance matrix
    std = np.sqrt(np.diag(cov))
    corr = cov / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(0.5 * (1.0 - corr))
    np.fill_diagonal(dist, 0.0)

    # Hierarchical clustering
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method=linkage_method)

    # Optimal cluster count
    n_clusters = _gap_statistic(dist, Z, B=50, seed=42)
    n_clusters = max(1, min(n_clusters, N))

    cluster_labels = fcluster(Z, n_clusters, criterion='maxclust')  # 1-based

    # Per-asset risk
    asset_risks = np.array([
        _compute_risk(returns.iloc[:, i].values, risk_measure, cvar_alpha)
        for i in range(N)
    ])
    # Guard against zero risk
    asset_risks = np.maximum(asset_risks, 1e-20)

    # Build dendrogram tree
    root = to_tree(Z)

    # Phase 1: top-down recursive bisection to cluster level
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
            alpha = 0.5
        else:
            # Inverse-risk: lower risk -> higher weight
            alpha = 1.0 - left_risk / total

        _bisect(node.get_left(), w * alpha)
        _bisect(node.get_right(), w * (1.0 - alpha))

    _bisect(root, 1.0)

    # Phase 2: naive risk parity within each cluster
    final_w = np.zeros(N)
    for cid, cw in cluster_weights.items():
        members = [i for i in range(N) if cluster_labels[i] == cid]
        inv = np.array([1.0 / asset_risks[i] for i in members])
        inv_total = inv.sum()
        for idx, m in enumerate(members):
            final_w[m] = cw * inv[idx] / inv_total

    # Normalise for floating-point safety
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
        description='Denoised HERC Portfolio Allocation')
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
