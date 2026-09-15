"""Forward variance curve construction and quadrature utilities."""
import numpy as np


def xi_curve_piecewise(expiries, w_in):
    """Build a piecewise-constant forward variance curve from total variances.

    Parameters
    ----------
    expiries : array_like
        Sorted expiry times.
    w_in : array_like
        Total variance w(T) = var_swap_rate * T at each expiry.
    """
    xi_vec_out = np.concatenate(
        ([w_in[0] / expiries[0]], np.diff(w_in) / np.diff(expiries))
    )

    def xi_curve_raw(t):
        if t <= expiries[-1]:
            return xi_vec_out[np.sum(expiries < t)]
        else:
            return xi_vec_out[-1]

    return np.vectorize(xi_curve_raw)


def gauss_legendre(a, b, n):
    """Gauss-Legendre quadrature nodes and weights on [a, b]."""
    knots, weights = np.polynomial.legendre.leggauss(n)
    knots_ab = 0.5 * (b - a) * knots + 0.5 * (b + a)
    weights_ab = 0.5 * (b - a) * weights
    return knots_ab, weights_ab
