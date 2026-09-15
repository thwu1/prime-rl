# Research Notes: Hierarchical Portfolio Allocation & Covariance Denoising

## Covariance Estimation Noise

For N assets observed over T periods, the sample covariance matrix contains
estimation noise that grows with N/T. When T is not much larger than N, a
substantial fraction of eigenvalues in the correlation matrix are noise-driven.

Random Matrix Theory (RMT) provides a framework for separating signal from
noise. The Marchenko-Pastur (MP) law describes the limiting eigenvalue
distribution of large random matrices. For a T×N matrix of i.i.d. entries
with variance σ², the eigenvalues of the sample correlation matrix are
supported on [λ₋, λ₊] where:

    λ± = σ² (1 ± √(N/T))²

The MP probability density function is:

    f(λ) = (T/N) / (2π σ²) · √((λ₊ − λ)(λ − λ₋)) / λ

for λ ∈ [λ₋, λ₊], and 0 otherwise.

The noise variance σ² can be estimated by fitting the MP density to the
empirical eigenvalue distribution (smoothed via KDE). The fit minimises
L2 distance between the KDE curve and the theoretical MP PDF over a grid
of λ values. For a correlation matrix, σ² is bounded in (0, 1].

**Constant-residual denoising**: eigenvalues at or below λ₊ are classified
as noise and replaced by their mean; the correlation matrix is reconstructed
from the modified spectrum and original eigenvectors, then rescaled so
diagonal entries equal 1. Convert back to covariance using original standard
deviations.

## Hierarchical Equal Risk Contribution (HERC)

HERC (Raffinot 2018) merges hierarchical clustering with risk-based allocation.

**Stage 1 — Clustering**: Agglomerative hierarchical clustering on a distance
metric derived from asset correlations: d(i,j) = √(½(1−ρ(i,j))). Supports
ward, single, complete, average linkage.

**Stage 2 — Cluster count**: Data-driven selection via the Gap statistic
(Tibshirani et al. 2001). Compares within-cluster dispersion W_k to its
expectation under a column-wise uniform reference distribution (B reference
samples). Gap(k) = E*[log W_k] − log W_k. Optimal k: smallest k where
Gap(k) ≥ Gap(k+1) − s_{k+1}, with s the standard error scaled by
√(1 + 1/B). W_k is computed as the sum over all clusters of (sum of
squared pairwise distances within the cluster) / (2 × cluster size).

**Stage 3 — Top-down bisection**: Traverse the dendrogram from root
downward. At each binary split, allocate weight to each sub-tree inversely
proportional to its total risk contribution (sum of individual asset risks
in the sub-tree). That is, the lower-risk sub-tree receives the larger
share of the weight. Recurse until each sub-tree maps to a single cluster.

**Stage 4 — Within-cluster NRP**: Naive Risk Parity within each leaf cluster:
weight each asset proportional to the inverse of its individual risk.

## Risk Measures

- **Variance** (ddof=1): sample variance with Bessel's correction.
- **Standard deviation** (ddof=1): square root of sample variance with
  Bessel's correction.
- **CVaR** (Conditional Value-at-Risk): sort returns ascending, take the
  worst ceil(n × α) observations, compute their negative mean. The result
  is positive for typical loss distributions. α is the tail probability
  (e.g. 0.05 for the 5% tail). Use ceil (not floor) so that even for
  small n × α at least one observation beyond the minimum is included
  when the product is non-integer.
