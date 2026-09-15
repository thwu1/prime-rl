"""
Newton-Schulz Iteration Analysis for the Muon Optimizer


Background:
The Muon optimizer orthogonalizes neural network weight update matrices using
a Newton-Schulz (NS) iteration. The quintic NS iteration applies:

    phi(x) = a*x + b*x^3 + c*x^5

repeatedly to the singular values of a matrix (after normalizing by Frobenius
norm so singular values lie in [0, 1]). After N iterations, all singular values
should be close to 1, producing an approximately orthogonal matrix.

The coefficient a = phi'(0) controls convergence speed for small singular values.
Larger a means faster convergence for small values, but can cause overshoot or
oscillation for values near 1. The optimization problem is to find coefficients
that maximize a while keeping the iterates within tolerance of 1.

Note: there is NO algebraic constraint like a+b+c=1. The only constraint is the
convergence criterion evaluated on a finite grid.
"""

import numpy as np


# Evaluation grid for coefficient optimization
EVAL_GRID = np.linspace(0.01, 1.0, 50000)


def phi_quintic(x, a, b, c):
    """Apply one step of the quintic NS polynomial."""
    return a * x + b * x**3 + c * x**5


def phi_septic(x, a, b, c, d):
    """Apply one step of the septic NS polynomial."""
    return a * x + b * x**3 + c * x**5 + d * x**7


def iterate_quintic(x, a, b, c, N):
    """Apply phi_quintic N times to array x (modifies x in place)."""
    for _ in range(N):
        x = phi_quintic(x, a, b, c)
    return x


def iterate_septic(x, a, b, c, d, N):
    """Apply phi_septic N times to array x."""
    for _ in range(N):
        x = phi_septic(x, a, b, c, d)
    return x


def max_deviation(values):
    """Compute max |values - 1| over the array. Returns inf if any NaN/Inf."""
    if np.any(np.isnan(values)) or np.any(np.isinf(values)):
        return float('inf')
    return float(np.max(np.abs(values - 1.0)))


def generate_test_matrix(seed=42):
    """
    Generate a deterministic 64x48 test matrix with controlled singular values.

    Singular values are log-uniformly spaced from exp(-3) ~ 0.05 to 1.0.
    Left/right singular vectors are random orthogonal matrices (seeded).
    """
    rng = np.random.RandomState(seed)
    U, _ = np.linalg.qr(rng.randn(64, 64))
    V, _ = np.linalg.qr(rng.randn(48, 48))
    sigma = np.exp(np.linspace(-3, 0, 48))
    S = np.zeros((64, 48))
    S[:48, :48] = np.diag(sigma)
    return U @ S @ V.T


def ns_orthogonalize_matrix(G, a, b, c, n_iters=5):
    """
    Apply Newton-Schulz iteration to approximately orthogonalize matrix G.

    Procedure (following the Muon optimizer):
    1. If G is tall (rows > cols), work with G^T
    2. Normalize by Frobenius norm
    3. Apply NS iteration: for each step, A = X @ X^T, B = b*A + c*A@A, X = a*X + B@X
    4. Transpose back if needed

    Returns the approximately orthogonal matrix (same shape as G).
    """
    X = G.astype(np.float64).copy()
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True

    # Normalize so singular values are in [0, 1]
    X = X / (np.linalg.norm(X, 'fro') + 1e-7)

    # Newton-Schulz iteration
    for _ in range(n_iters):
        A = X @ X.T
        B = b * A + c * A @ A
        X = a * X + B @ X

    if transposed:
        X = X.T

    return X


# =============================================================================
# OUTPUT FORMAT: Write results to /app/results.json
# =============================================================================
#
# {
#   "quintic": {
#     "a": <float>,
#     "b": <float>,
#     "c": <float>,
#     "convergence_profile": [<float>, ..., <float>]  // 20 values: max deviation at N=1..20
#   },
#   "septic": {
#     "a": <float>,
#     "b": <float>,
#     "c": <float>,
#     "d": <float>
#   },
#   "fixed_points": [
#     {"x": 0.0, "phi_prime": <float>},
#     {"x": <float>, "phi_prime": <float>},
#     ...
#   ],
#   "matrix_analysis": {
#     "frobenius_error": <float>,
#     "max_sv_deviation": <float>
#   }
# }
