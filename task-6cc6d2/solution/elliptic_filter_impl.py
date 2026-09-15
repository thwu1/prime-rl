"""
Elliptic (Cauer) filter design from scratch using Jacobian elliptic functions
and Landen transformations.


References:
  Vadim Zavalishin, "The Art of VA Filter Design", Chapter 9.
  Orfanidis, "Lecture Notes on Elliptic Filter Design".
  Lutovac, Tosic, Evans, "Filter Design for Signal Processing".
"""

import numpy as np

_LANDEN_STEPS = 14


# ══════════════════════════════════════════════════════════════════════════════
# Complete elliptic integral K(k) — takes modulus k, not parameter m=k²
# ══════════════════════════════════════════════════════════════════════════════

def complete_elliptic_K(k):
    """K(k) via descending Landen transformations."""
    k = float(k)
    if k <= 0:
        return np.pi / 2
    if k >= 1:
        return float('inf')
    K = np.pi / 2.0
    for _ in range(_LANDEN_STEPS):
        kp = np.sqrt(1.0 - k * k)
        k = (k / (1.0 + kp)) ** 2
        K = K * (1.0 + k)
    return float(K)


# ══════════════════════════════════════════════════════════════════════════════
# Jacobian elliptic functions — modulus convention
# ══════════════════════════════════════════════════════════════════════════════

def _landen_sequence(k, steps=_LANDEN_STEPS):
    """Build descending Landen sequence from modulus k."""
    ks = [k]
    kc = k
    for _ in range(steps):
        kcp = np.sqrt(1.0 - kc * kc)
        kc = (kc / (1.0 + kcp)) ** 2
        ks.append(kc)
    return ks


def cd_jacobi(u, k):
    """Jacobian elliptic cosine cd(u, k) via ascending Landen recursion."""
    k = float(k)
    if k < 1e-15:
        return np.cos(u)
    if k > 1.0 - 1e-15:
        return 1.0 / np.cosh(u)
    K = complete_elliptic_K(k)
    x = u / K
    ks = _landen_sequence(k)
    y = np.cos(np.pi / 2.0 * x)
    for i in range(len(ks) - 1, 0, -1):
        kn = ks[i]
        y = (1.0 + kn) * y / (1.0 + kn * y * y)
    return y


def sn_jacobi(u, k):
    """Jacobian elliptic sine sn(u, k) via ascending Landen recursion."""
    k = float(k)
    if k < 1e-15:
        return np.sin(u)
    if k > 1.0 - 1e-15:
        return np.tanh(u)
    K = complete_elliptic_K(k)
    x = u / K
    ks = _landen_sequence(k)
    y = np.sin(np.pi / 2.0 * x)
    for i in range(len(ks) - 1, 0, -1):
        kn = ks[i]
        y = (1.0 + kn) * y / (1.0 + kn * y * y)
    return y


def _dn_from_sn(sn_val, k):
    """Compute dn from sn using dn² = 1 - k²·sn²."""
    return np.sqrt(1.0 - k * k * sn_val * sn_val)


def _cn_from_sn(sn_val):
    """Compute cn from sn using cn² = 1 - sn²."""
    return np.sqrt(1.0 - sn_val * sn_val)


# ══════════════════════════════════════════════════════════════════════════════
# Inverse Jacobian elliptic functions
# ══════════════════════════════════════════════════════════════════════════════

def _complement(kx):
    """Compute sqrt(1 - kx²) robustly."""
    return np.sqrt((1.0 - kx) * (1.0 + kx))


def sn_inverse(y, k):
    """
    Compute x = sn^{-1}(y, k) via descending Landen recursion.
    Supports complex y. Uses modulus k (not parameter m).
    """
    k = float(k)
    if k < 1e-15:
        return np.arcsin(complex(y))
    if k >= 1.0 - 1e-15:
        return np.arctanh(complex(y))

    # Build descending Landen sequence
    ks = [k]
    kc = k
    while True:
        kcp = _complement(kc)
        kc_new = (kc / (1.0 + kcp)) ** 2
        ks.append(float(np.real(kc_new)))
        kc = kc_new
        if kc_new == 0 or len(ks) > _LANDEN_STEPS + 1:
            break

    # Compute K
    K = np.pi / 2.0
    for ki in ks[1:]:
        K *= (1.0 + ki)

    # Descend the function value
    yv = complex(y)
    for i in range(len(ks) - 1):
        kn = ks[i]
        knext = ks[i + 1]
        yv = 2.0 * yv / ((1.0 + knext) * (1.0 + _complement(kn * yv)))

    u = (2.0 / np.pi) * np.arcsin(yv)
    return K * u


def cd_inverse(y, k):
    """
    Compute x = cd^{-1}(y, k) via the relation cd^{-1}(y) = K - sn^{-1}(y).
    Supports complex y.
    """
    k = float(k)
    if k < 1e-15:
        return np.arccos(complex(y))
    K = complete_elliptic_K(k)
    return K - sn_inverse(complex(y), k)


# ══════════════════════════════════════════════════════════════════════════════
# Degree equation solver
# ══════════════════════════════════════════════════════════════════════════════

def _ellipdeg(N, m1):
    """
    Solve the degree equation n*K(m)/K'(m) = K(m1)/K'(m1) for m.
    Uses the nome-based approach from Orfanidis.
    m1 is the PARAMETER (k1²).
    Returns m (parameter, k²).
    """
    K1 = complete_elliptic_K(np.sqrt(m1))
    K1p = complete_elliptic_K(np.sqrt(1.0 - m1))

    q1 = np.exp(-np.pi * K1p / K1)
    q = q1 ** (1.0 / N)

    # Compute m from q using the formula from Orfanidis eq. 49
    MMAX = 10
    mnum = np.arange(MMAX + 1)
    mden = np.arange(1, MMAX + 2)

    num = np.sum(q ** (mnum * (mnum + 1)))
    den = 1.0 + 2.0 * np.sum(q ** (mden ** 2))

    return float(16.0 * q * (num / den) ** 4)


# ══════════════════════════════════════════════════════════════════════════════
# Elliptic filter design
# ══════════════════════════════════════════════════════════════════════════════

def elliptic_filter_design(N, rp, rs):
    """
    Design the analog prototype of a lowpass elliptic filter.

    Parameters
    ----------
    N : int
        Filter order.
    rp : float
        Passband ripple in dB.
    rs : float
        Stopband attenuation in dB.

    Returns
    -------
    zeros : ndarray of complex
    poles : ndarray of complex
    gain : float
    """
    eps_sq = 10.0 ** (rp / 10.0) - 1.0
    eps = np.sqrt(eps_sq)

    # Discrimination parameter: k1² = ε² / (10^(rs/10) - 1)
    ck1_sq = eps_sq / (10.0 ** (rs / 10.0) - 1.0)

    # Solve degree equation for m (= k²)
    m = _ellipdeg(N, ck1_sq)
    k = np.sqrt(m)

    # K(k) — complete elliptic integral of selectivity modulus
    capk = complete_elliptic_K(k)

    # Zeros: at u_j = j*K/N for j = 1, 3, 5, ... (first L odd integers)
    j_indices = np.arange(1 - N % 2, N, 2)
    jj = len(j_indices)

    # Compute sn at the zero locations
    sn_vals = np.array([float(np.real(sn_jacobi(ji * capk / N, k))) for ji in j_indices])

    # Filter out negligible values (for odd N, j=0 gives sn=0)
    snew = sn_vals[np.abs(sn_vals) > 1e-14]

    # Transfer function zeros on imaginary axis
    z = 1.0 / (np.sqrt(m) * snew)
    z = 1j * z
    z = np.concatenate((z, np.conj(z)))

    # Pole computation
    # r = Im(sn^{-1}(j/ε, k1)) where k1² = ck1_sq
    k1 = np.sqrt(ck1_sq)
    K_k1 = complete_elliptic_K(k1)

    # Compute r via sn_inverse at complex argument
    z_complex = sn_inverse(1j / eps, k1)
    r = float(z_complex.imag)

    # v0 = K(k) * r / (N * K(k1))
    v0 = capk * r / (N * K_k1)

    # Compute elliptic functions at the zero positions and at v0
    # s[i] = sn(u_i, k), c[i] = cn(u_i, k), d[i] = dn(u_i, k)
    s_arr = np.array([float(np.real(sn_jacobi(ji * capk / N, k))) for ji in j_indices])
    c_arr = np.array([float(np.real(_cn_from_sn(si))) for si in s_arr])
    d_arr = np.array([float(np.real(_dn_from_sn(si, k))) for si in s_arr])

    # sv, cv, dv at v0 with complementary modulus k' = sqrt(1-m)
    kp = np.sqrt(1.0 - m)
    sv = float(np.real(sn_jacobi(v0, kp)))
    cv = float(np.real(cd_jacobi(v0, kp)))  # cd = cn/dn; but we need cn and dn separately
    # Actually need cn(v0, k') and dn(v0, k') separately
    sv_val = float(np.real(sn_jacobi(v0, kp)))
    cv_val = float(np.real(_cn_from_sn(sv_val)))  # cn(v0, k')
    dv_val = float(np.real(_dn_from_sn(sv_val, kp)))  # dn(v0, k')

    # Pole formula (Lutovac/Orfanidis):
    # p_i = -(c_i * d_i * sv * cv + j * s_i * dv) / (1 - (d_i * sv)²)
    p = -(c_arr * d_arr * sv_val * cv_val + 1j * s_arr * dv_val) / (1.0 - (d_arr * sv_val) ** 2)

    # For odd N: keep the real pole and complex pairs
    if N % 2:
        # p contains (N+1)/2 entries: 1 real + (N-1)/2 complex
        # The complex ones need conjugate pairs
        newp = p[np.abs(p.imag) > 1e-14 * np.sqrt(np.sum(np.abs(p) ** 2))]
        p = np.concatenate((p, np.conj(newp)))
    else:
        p = np.concatenate((p, np.conj(p)))

    # Gain: prod(-p) / prod(-z), adjusted for even order
    k_gain = float((np.prod(-p) / np.prod(-z)).real)
    if N % 2 == 0:
        k_gain = k_gain / np.sqrt(1.0 + eps_sq)

    return z, p, k_gain
