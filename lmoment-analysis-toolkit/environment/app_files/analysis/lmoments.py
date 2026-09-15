"""
L-moment estimation via Probability Weighted Moments (PWM).
Implements Hosking (1990) unbiased estimators for sample L-moments.
"""
import numpy as np
from math import comb


def sample_lmoments(x, nmom=4):
    """Compute unbiased sample L-moments via PWM estimators.

    Parameters
    ----------
    x : array_like
        Sample data (any order).
    nmom : int
        Number of L-moments (default: 4).

    Returns
    -------
    numpy.ndarray
        L-moments [l1, l2, ..., l_nmom].
    """
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)

    # Probability Weighted Moments
    # beta_r = (1/n) * sum_{i=r}^{n-1} C(i,r) / C(n-1,r) * x_{i:n}
    betas = np.zeros(nmom)
    for r in range(nmom):
        s = 0.0
        norm = comb(n, r)
        for i in range(r, n):
            s += comb(i, r) / norm * x[i]
        betas[r] = s / n

    # Convert PWMs to L-moments via shifted Legendre polynomial coefficients
    # lambda_r = sum_{k=0}^{r-1} p_{r-1,k} * beta_k
    lmoms = np.zeros(nmom)
    for r in range(1, nmom + 1):
        val = 0.0
        for k in range(r):
            coeff = (-1) ** (r - 1 - k) * comb(r - 1, k) * comb(r - 1 + k, k)
            val += coeff * betas[k]
        lmoms[r - 1] = val
    return lmoms
