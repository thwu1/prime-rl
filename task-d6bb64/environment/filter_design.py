"""Elliptic (Cauer) lowpass filter design from first principles."""

import numpy as np
from elliptic_k import complete_elliptic_K
from jacobi_cd import elliptic_cd
from cd_inverse import elliptic_cd_inv


def _sn(u, k):
    """Jacobian sn(u, k) derived from cd: sn(u) = cd(u - K)."""
    K = complete_elliptic_K(k)
    return elliptic_cd(u - K, k)


def _cn_dn(u, k):
    """Compute cn(u,k) and dn(u,k) from cd and sn."""
    s = _sn(u, k)
    c_over_d = elliptic_cd(u, k)
    dn2 = 1.0 - k ** 2 * s ** 2
    dn = np.sqrt(dn2)
    cn = c_over_d * dn
    return cn, dn


def _sc(u, k):
    """Jacobian sc(u, k) = sn(u)/cn(u)."""
    s = _sn(u, k)
    cn, _ = _cn_dn(u, k)
    if abs(cn) < 1e-30:
        return complex(1e15) * np.sign(np.real(s))
    return s / cn


def _solve_degree_equation_for_k(N, k1):
    """Solve K'(k)/K(k) = (1/N) * K'(k1)/K(k1) for k (selectivity).

    Parameters
    ----------
    N : int
        Filter order.
    k1 : float
        Discrimination parameter (epsilon_p / epsilon_s).

    Returns
    -------
    float
        Selectivity parameter k.
    """
    k1p = np.sqrt(1.0 - k1 * k1)
    K_k1 = complete_elliptic_K(k1)
    K_k1p = complete_elliptic_K(k1p)
    target = K_k1p / (N * K_k1)

    lo, hi = 1e-18, 1.0 - 1e-15
    for _ in range(200):
        mid = (lo + hi) / 2.0
        K_mid = complete_elliptic_K(mid)
        midp = np.sqrt(1.0 - mid * mid)
        K_midp = complete_elliptic_K(midp)
        ratio = K_midp / K_mid
        if ratio > target:
            lo = mid
        else:
            hi = mid
        if abs(ratio - target) / (abs(target) + 1e-30) < 1e-14:
            break
    return (lo + hi) / 2.0


def design_elliptic_lowpass(N, ripple_db, stopband_db, omega_s=None):
    """Design an N-th order analog elliptic lowpass filter prototype.

    Passband edge is normalized to 1 rad/s.

    Parameters
    ----------
    N : int
        Filter order.
    ripple_db : float
        Maximum passband ripple in dB.
    stopband_db : float
        Minimum stopband attenuation in dB.
    omega_s : float, optional
        Stopband edge frequency (derived internally if not given).

    Returns
    -------
    zeros : ndarray
        Transfer function zeros (on imaginary axis).
    poles : ndarray
        Transfer function poles (left half-plane).
    gain : float
        Overall gain factor.
    """
    N = int(N)
    epsilon_p = np.sqrt(10.0 ** (ripple_db / 10.0) - 1.0)
    epsilon_s = np.sqrt(10.0 ** (stopband_db / 10.0) - 1.0)

    k1 = epsilon_p / epsilon_s
    k1p = np.sqrt(1.0 - k1 * k1)

    k = _solve_degree_equation_for_k(N, k1)
    kp = np.sqrt(1.0 - k * k)

    K = complete_elliptic_K(k)
    Kp = complete_elliptic_K(kp)
    K1 = complete_elliptic_K(k1)
    K1p = complete_elliptic_K(k1p)

    # Transfer function zeros: at poles of R_N(omega)
    L = N // 2
    zeros_s = []
    for m in range(L):
        u_m = (2 * m + 1) * K / N
        cd_val = np.real(elliptic_cd(u_m, k))
        omega_z = 1.0 / (k * cd_val)
        zeros_s.append(1j * omega_z)
        zeros_s.append(-1j * omega_z)

    # Find w0 such that sc(w0, k1') = 1/epsilon_p
    target_sc = 1.0 / epsilon_p
    w_lo, w_hi = 1e-15, K1p * (1.0 - 1e-10)
    for _ in range(200):
        w_mid = (w_lo + w_hi) / 2.0
        sc_val = np.real(_sc(w_mid, k1p))
        if sc_val < target_sc:
            w_lo = w_mid
        else:
            w_hi = w_mid
        if abs(sc_val - target_sc) / (abs(target_sc) + 1e-20) < 1e-13:
            break
    w0 = (w_lo + w_hi) / 2.0

    sigma = w0 * K / (N * K1p)

    # Compute poles via cd with imaginary shift
    poles = []
    for n in range(N):
        u_n = (2 * n + 1) * K / N
        omega_n = elliptic_cd(complex(u_n, -sigma), k)
        s_n = 1j * omega_n
        poles.append(s_n)

    # Enforce conjugate symmetry
    final_poles = []
    for n in range(N):
        m_idx = N - 1 - n
        if n < m_idx:
            p = poles[n]
            final_poles.append(p)
            final_poles.append(np.conj(p))
        elif n == m_idx:
            p = poles[n]
            final_poles.append(complex(np.real(p), 0.0))

    poles = np.array(final_poles)
    zeros = np.array(zeros_s) if zeros_s else np.array([], dtype=complex)

    # Gain normalization
    if N % 2 == 1:
        H0 = 1.0
    else:
        H0 = 1.0 / np.sqrt(1.0 + epsilon_p ** 2)

    prod_neg_z = np.prod(-zeros) if len(zeros) > 0 else 1.0
    prod_neg_p = np.prod(-poles)
    gain = abs(np.real(H0 * prod_neg_p / prod_neg_z))

    return zeros, poles, gain
