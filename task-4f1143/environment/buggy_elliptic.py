"""
Elliptic filter design from scratch with C backend for core computations.

"""

import cmath
import ctypes
import math
import numpy as np

# Load C shared library for elliptic integral computation
_lib = ctypes.CDLL("/app/libelliptic.so")
_lib.ellipk_c.argtypes = [ctypes.c_double,
                           ctypes.POINTER(ctypes.c_double),
                           ctypes.POINTER(ctypes.c_double)]
_lib.ellipk_c.restype = None
_lib.cd_c.argtypes = [ctypes.c_double, ctypes.c_double]
_lib.cd_c.restype = ctypes.c_double

_LANDEN_MAX = 40


def _complement(k):
    """sqrt(1 - k^2) computed carefully for small k."""
    return math.sqrt((1 - k) * (1 + k))


# ──────────────────────────────────────────────────────────────
# 1. Complete elliptic integral K(k) via C shared library
# ──────────────────────────────────────────────────────────────

def ellipk(k):
    """
    Complete elliptic integral K(k) and K'(k) via C shared library.
    Returns (K, K') where K' = K(sqrt(1-k^2)).
    """
    K_out = ctypes.c_double()
    Kp_out = ctypes.c_double()
    _lib.ellipk_c(k, ctypes.byref(K_out), ctypes.byref(Kp_out))
    return K_out.value, Kp_out.value


# ──────────────────────────────────────────────────────────────
# 2. Landen sequence (needed in Python for cd with complex args)
# ──────────────────────────────────────────────────────────────

def _landen_descending(k):
    """Build descending Landen sequence from k toward 0."""
    ks = [k]
    kn = k
    for _ in range(_LANDEN_MAX):
        if kn == 0:
            break
        kp = _complement(kn)
        kn_next = ((kn / (1.0 + kp)) ** 2) if (1.0 + kp) != 0 else 0
        ks.append(kn_next)
        if kn_next == 0:
            break
        kn = kn_next
    return ks


# ──────────────────────────────────────────────────────────────
# 3. cd(u, k) — normalized so quarter-period = 1
# ──────────────────────────────────────────────────────────────

def cd(u, k):
    """
    Jacobian elliptic function cd(u, k) with u normalized (quarter-period = 1).
    Handles complex u.
    """
    if k == 0:
        if isinstance(u, complex):
            return cmath.cos(cmath.pi / 2 * u)
        return math.cos(math.pi / 2 * u)

    ks = _landen_descending(k)

    if isinstance(u, complex):
        y = cmath.cos(cmath.pi / 2 * u)
    else:
        y = complex(math.cos(math.pi / 2 * u))

    for i in range(len(ks) - 2, -1, -1):
        kn = ks[i + 1]
        y = (1.0 + kn) * y / (1.0 + kn * y)

    if isinstance(u, (int, float)) and abs(y.imag) < 1e-14:
        return y.real
    return y


# ──────────────────────────────────────────────────────────────
# 4. Inverse Jacobian sn via Landen
# ──────────────────────────────────────────────────────────────

def _arc_jac_sn(w, m):
    """
    Inverse Jacobian sn: solve w = sn(z, m) for z.
    m = k^2 is the parameter. w can be complex.
    Returns z in actual units.
    """
    k = math.sqrt(m)

    if k > 1:
        return float('nan')
    if k == 1:
        if isinstance(w, complex):
            return cmath.atanh(w)
        return math.atanh(w)

    ks = _landen_descending(k)

    K = math.pi / 2
    for ki in ks[1:]:
        K *= (1 + ki)

    wns = [w]
    for i in range(len(ks) - 1):
        kn = ks[i]
        knext = ks[i + 1]
        wn = wns[-1]
        kn_wn = kn * wn
        if isinstance(kn_wn, complex):
            sq = cmath.sqrt(1.0 - kn_wn * kn_wn)
        else:
            val = 1.0 - kn_wn * kn_wn
            sq = cmath.sqrt(val) if val < 0 else math.sqrt(val)
        denom = (1.0 + knext) * (1.0 + sq)
        wnext = 2.0 * wn / denom
        wns.append(wnext)

    w_final = wns[-1]
    if isinstance(w_final, complex):
        u = 2.0 / cmath.pi * cmath.asin(w_final)
    else:
        u = 2.0 / math.pi * math.asin(w_final)

    return K * u


def _arc_jac_sc1(w, m):
    """
    Real inverse Jacobian sc with complementary modulus.
    Solve w = sc(z, 1-m). w is real, m is the original modulus parameter.
    Returns real z.
    """
    z = _arc_jac_sn(1j * w, m)
    if isinstance(z, complex):
        return z.imag
    return 0.0


# ──────────────────────────────────────────────────────────────
# 5. cd_inv(w, k) via Landen
# ──────────────────────────────────────────────────────────────

def cd_inv(w, k):
    """
    Inverse cd: find u (normalized, quarter-period=1) such that cd(u, k) = w.
    """
    if k == 0:
        if isinstance(w, complex):
            return 2.0 / cmath.pi * cmath.acos(w)
        return 2.0 / math.pi * math.acos(max(-1.0, min(1.0, w)))

    w = complex(w)

    sn_sq = (1.0 - w * w) / (1.0 - k * k * w * w)
    sn_val = cmath.sqrt(sn_sq)

    K_val, _ = ellipk(k)
    z_actual = _arc_jac_sn(sn_val, k * k)

    u = z_actual / K_val

    return u


# ──────────────────────────────────────────────────────────────
# 6. Degree equation solver
# ──────────────────────────────────────────────────────────────

def ellipdeg(n, m1):
    """
    Given n and m1, solve: n * K'(sqrt(m))/K(sqrt(m)) = K'(sqrt(m1))/K(sqrt(m1)) for m.
    Uses nomes. m = k^2, m1 = k1^2.
    """
    k1 = math.sqrt(m1)
    K1, K1p = ellipk(k1)

    q1 = math.exp(-math.pi * K1p / K1)
    q = q1 ** (1.0 / n)

    M = 7
    num = sum(q ** (m * (m + 1)) for m in range(M + 1))
    den = 1.0 + 2.0 * sum(q ** (m * m) for m in range(1, M + 2))

    return 16.0 * q * (num / den) ** 4


# ──────────────────────────────────────────────────────────────
# 7. Elliptic rational function R_N(x, k)
# ──────────────────────────────────────────────────────────────

def elliptic_rational(x, N, k):
    """
    Degree-N elliptic rational function R_N(x, k).
    Returns (R_N(x), k_tilde) where k_tilde satisfies the degree equation.
    """
    m = k * k

    m_tilde = ellipdeg(N, m)
    k_tilde = math.sqrt(m_tilde)

    K_k, _ = ellipk(k)
    K_kt, _ = ellipk(k_tilde)

    u = cd_inv(x, k)
    v = N * (K_kt / K_k) * u
    result = cd(v, k_tilde)

    if isinstance(x, (int, float)):
        if isinstance(result, complex):
            result = result.real
    return result, k_tilde


# ──────────────────────────────────────────────────────────────
# 8. elliptic_filter(N, Rp, Rs) — analog prototype
# ──────────────────────────────────────────────────────────────

def _pow10m1(x):
    """10^x - 1, computed carefully."""
    return 10.0 ** x - 1.0


def _ellipj(u_actual, m):
    """
    Jacobian elliptic functions sn(u,m), cn(u,m), dn(u,m).
    u_actual is in actual units (not normalized). m = k^2.
    """
    k = math.sqrt(m) if m > 0 else 0.0

    if k == 0:
        return math.sin(u_actual), math.cos(u_actual), 1.0

    K_val, _ = ellipk(k)
    u_norm = u_actual / K_val

    cd_val = cd(u_norm, k)
    if isinstance(cd_val, complex):
        cd_val = cd_val.real

    sn_sq = (1.0 - cd_val * cd_val) / (1.0 - k * k * cd_val * cd_val)
    sn_sq = max(0.0, min(1.0, sn_sq))
    sn_val = math.sqrt(sn_sq)

    dn_sq = 1.0 - m * sn_sq
    dn_val = math.sqrt(max(0.0, dn_sq))

    cn_val = cd_val * dn_val

    u_mod = u_norm % 4.0
    if u_mod > 2.0:
        sn_val = -sn_val

    if 1.0 < u_mod < 3.0:
        cn_val = -abs(cn_val)
    else:
        cn_val = abs(cn_val)

    return sn_val, cn_val, dn_val


def _ellipj_array(u_array, m):
    """Vectorized ellipj for arrays."""
    sn = np.zeros_like(u_array)
    cn = np.zeros_like(u_array)
    dn = np.zeros_like(u_array)
    for i, u in enumerate(u_array):
        sn[i], cn[i], dn[i] = _ellipj(float(u), m)
    return sn, cn, dn


def elliptic_filter(N, Rp, Rs):
    """
    Design an Nth-order analog lowpass elliptic (Cauer) filter prototype.

    Parameters
    ----------
    N : int - Filter order (>= 2)
    Rp : float - Passband ripple in dB
    Rs : float - Stopband attenuation in dB

    Returns
    -------
    z : ndarray - Zeros (on imaginary axis)
    p : ndarray - Poles (left half-plane)
    k : float - Gain
    """
    eps_sq = _pow10m1(0.1 * Rp)
    eps = math.sqrt(eps_sq)

    ck1_sq = eps_sq / _pow10m1(0.1 * Rs)

    m = ellipdeg(N, ck1_sq)

    k_sel = math.sqrt(m)
    K_sel, _ = ellipk(k_sel)

    EPSILON = 2e-16
    j_indices = np.arange(1 - N % 2, N, 2)

    s_arr, c_arr, d_arr = _ellipj_array(j_indices * K_sel / N, m)

    snew = s_arr[np.abs(s_arr) > EPSILON]
    z = 1.0 / (math.sqrt(m) * snew)
    z = 1j * z
    z = np.concatenate((z, np.conjugate(z)))

    r = _arc_jac_sc1(1.0 / eps, ck1_sq)

    k1 = math.sqrt(ck1_sq)
    K1, _ = ellipk(k1)
    v0 = K_sel * r / (N * K1)

    sv, cv, dv = _ellipj(v0, 1.0 - m)

    p = -(c_arr * d_arr * sv * cv + 1j * s_arr * dv) / (1.0 - (d_arr * sv) ** 2)

    if N % 2:
        newp = p[np.abs(p.imag) > EPSILON * math.sqrt(np.sum(np.abs(p) ** 2))]
        p = np.concatenate((p, np.conjugate(newp)))
    else:
        p = np.concatenate((p, np.conjugate(p)))

    k_gain = (np.prod(-p) / np.prod(-z)).real
    if N % 2 == 1:
        k_gain = k_gain / math.sqrt(1.0 + eps_sq)

    return z, p, k_gain


# ──────────────────────────────────────────────────────────────
# 9. discretize_elliptic(N, Rp, Rs, fs, fc) — digital IIR filter
# ──────────────────────────────────────────────────────────────

def discretize_elliptic(N, Rp, Rs, fs, fc):
    """
    Design an Nth-order digital lowpass elliptic filter.

    Uses the analog prototype from elliptic_filter(), applies frequency
    pre-warping and the bilinear transform, then factors into cascaded
    second-order sections.

    Parameters
    ----------
    N : int - Filter order
    Rp : float - Passband ripple in dB
    Rs : float - Stopband attenuation in dB
    fs : float - Sample rate in Hz
    fc : float - Cutoff frequency in Hz (must be < fs/2)

    Returns
    -------
    sos : ndarray of shape (ceil(N/2), 6)
        Second-order sections [b0, b1, b2, a0, a1, a2] with a0=1.
    """
    raise NotImplementedError(
        "discretize_elliptic is not yet implemented. "
        "Implement bilinear transform discretization with pre-warping "
        "and ZPK-to-SOS conversion."
    )
