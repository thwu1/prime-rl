"""
Elliptic (Cauer) analog lowpass filter design — implementation required.

This module must provide a complete from-scratch implementation of elliptic
filter design. See reference_data/ for expected outputs and tools/validate.py
for accuracy requirements.

IMPORTANT: The following libraries are FORBIDDEN in this module:
  - scipy.signal
  - scipy.special
  - mpmath
  - Any library that provides elliptic functions, elliptic integrals,
    or filter design routines

Only numpy (for basic array/complex arithmetic) and the Python standard
library are permitted.
"""

import numpy as np


def complete_elliptic_K(k):
    """
    Complete elliptic integral of the first kind K(k).

    Takes modulus k (NOT parameter m = k^2) in the interval (0, 1).
    Returns a float.

    Must be accurate to at least 12 significant digits for k in [1e-6, 1-1e-6].
    Must satisfy: K(k) -> pi/2 as k -> 0, and K(k) -> infinity as k -> 1.
    """
    raise NotImplementedError("complete_elliptic_K not yet implemented")


def cd_jacobi(u, k):
    """
    Jacobian elliptic function cd(u, k).

    Takes argument u (float or complex) and modulus k in (0, 1).
    Must satisfy:
      cd(0, k) = 1
      cd(K(k), k) = 0
      cd(-u, k) = cd(u, k)  (even function)
      cd(u + 4K, k) = cd(u, k)  (periodicity)
    """
    raise NotImplementedError("cd_jacobi not yet implemented")


def sn_jacobi(u, k):
    """
    Jacobian elliptic function sn(u, k).

    Takes argument u (float or complex) and modulus k in (0, 1).
    Must satisfy:
      sn(0, k) = 0
      sn(K(k), k) = 1
      sn(-u, k) = -sn(u, k)  (odd function)
    """
    raise NotImplementedError("sn_jacobi not yet implemented")


def cd_inverse(y, k):
    """
    Inverse of the Jacobian elliptic cd function.

    Given y = cd(x, k), returns x. Must handle complex y.
    Must satisfy:
      cd_inverse(1, k) = 0
      cd_inverse(0, k) = K(k)
    """
    raise NotImplementedError("cd_inverse not yet implemented")


def sn_inverse(y, k):
    """
    Inverse of the Jacobian elliptic sn function.

    Given y = sn(x, k), returns x. Must handle complex y.
    Must satisfy:
      sn_inverse(0, k) = 0
      sn_inverse(1, k) = K(k)
    """
    raise NotImplementedError("sn_inverse not yet implemented")


def elliptic_filter_design(N, rp, rs):
    """
    Design the analog prototype of a lowpass elliptic (Cauer) filter.

    Parameters
    ----------
    N : int
        Filter order (positive integer >= 3).
    rp : float
        Passband ripple in dB (e.g. 1.0 means 1 dB ripple).
    rs : float
        Stopband attenuation in dB (e.g. 40.0 means 40 dB attenuation).

    Returns
    -------
    zeros : 1-D numpy array of complex
        Transfer function zeros.
    poles : 1-D numpy array of complex
        Transfer function poles (must all have negative real parts).
    gain : float
        Scalar gain factor.

    The returned (zeros, poles, gain) define H(s) = gain * prod(s - z_i) / prod(s - p_i).

    Requirements (see reference_data/ for examples):
      - Passband: |H(jw)| oscillates between 1 and 10^(-rp/20) for w in [0, 1]
      - Stopband: |H(jw)| <= 10^(-rs/20) for w beyond the stopband edge
      - All poles in the open left half-plane
      - Zeros on the imaginary axis
      - Odd N: unity DC gain, one real pole, N-1 complex zeros in conjugate pairs
      - Even N: DC gain = 10^(-rp/20), all poles/zeros complex in conjugate pairs
    """
    raise NotImplementedError("elliptic_filter_design not yet implemented")
