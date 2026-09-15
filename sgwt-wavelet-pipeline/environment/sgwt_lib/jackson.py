"""Jackson-Chebyshev coefficients for ideal band-pass approximation."""
import numpy as np


def compute_jackson_cheby_coeff(filter_bounds, delta_lambda, m):
    """Compute Jackson-damped Chebyshev coefficients for an ideal band-pass.

    Approximates the indicator function of ``[filter_bounds[0], filter_bounds[1]]``
    using a truncated Chebyshev expansion with Jackson damping to reduce
    Gibbs oscillations.

    Parameters
    ----------
    filter_bounds : list [a, b]
        Pass-band edge frequencies.
    delta_lambda : list [lambda_min, lambda_max]
        Eigenvalue spectrum range.
    m : int
        Polynomial order.

    Returns
    -------
    coefficients : ndarray (m + 1,)
        Jackson-damped Chebyshev polynomial coefficients.
    """
    raise NotImplementedError(
        "Jackson-Chebyshev coefficient computation not yet implemented. "
        "See /app/docs/polynomial_approximation.md for the mathematical "
        "specification."
    )
