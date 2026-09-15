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
        y = (1.0 + kn) * y / (1.0 + kn * y * y)

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
    if N % 2 == 0:
        k_gain = k_gain / math.sqrt(1.0 + eps_sq)

    return z, p, k_gain


# ──────────────────────────────────────────────────────────────
# 9. discretize_elliptic(N, Rp, Rs, fs, fc) — digital IIR filter
# ──────────────────────────────────────────────────────────────

def _split_conjugate_pairs(arr, tol=1e-10):
    """Separate complex array into conjugate pairs and real values.

    Returns (pairs, reals) where pairs is a list of (z, conj(z)) tuples
    and reals is a list of floats.
    """
    arr = np.array(arr, dtype=complex)
    pairs = []
    reals = []
    used = np.zeros(len(arr), dtype=bool)

    for i in range(len(arr)):
        if used[i]:
            continue
        if abs(arr[i].imag) <= tol:
            reals.append(arr[i].real)
            used[i] = True
        else:
            found = False
            for j in range(i + 1, len(arr)):
                if not used[j] and abs(arr[i] - arr[j].conjugate()) < tol:
                    pairs.append((arr[i], arr[j]))
                    used[i] = True
                    used[j] = True
                    found = True
                    break
            if not found:
                pairs.append((arr[i], arr[i].conjugate()))
                used[i] = True

    return pairs, reals


def _zpk2sos(z, p, k):
    """Convert zeros, poles, gain to cascaded second-order sections.

    Uses nearest pole-zero pairing. Sections are ordered with poles
    farthest from the unit circle first (for numerical stability in
    direct-form implementation).
    """
    z = np.array(z, dtype=complex)
    p = np.array(p, dtype=complex)

    p_pairs, p_reals = _split_conjugate_pairs(p)
    z_pairs, z_reals = _split_conjugate_pairs(z)

    z_pairs = list(z_pairs)
    z_reals = list(z_reals)

    sections = []

    # Sort complex pole pairs: farthest from unit circle first
    p_pairs.sort(key=lambda pp: -abs(abs(pp[0]) - 1.0))

    for pp in p_pairs:
        # Find nearest zero pair by distance
        if z_pairs:
            dists = [min(abs(pp[0] - zp[0]), abs(pp[0] - zp[1]))
                     for zp in z_pairs]
            idx = int(np.argmin(dists))
            zz = z_pairs.pop(idx)
        elif len(z_reals) >= 2:
            zz = (z_reals.pop(), z_reals.pop())
        else:
            zz = (-1.0 + 0j, -1.0 + 0j)

        b0 = 1.0
        b1 = -(zz[0] + zz[1]).real
        b2 = (zz[0] * zz[1]).real
        a0 = 1.0
        a1 = -(pp[0] + pp[1]).real
        a2 = (pp[0] * pp[1]).real
        sections.append([b0, b1, b2, a0, a1, a2])

    # Pair up real poles
    p_reals_left = list(p_reals)
    while len(p_reals_left) >= 2:
        p0 = p_reals_left.pop()
        p1 = p_reals_left.pop()

        if z_pairs:
            zz = z_pairs.pop(0)
            z0, z1 = complex(zz[0]), complex(zz[1])
        elif len(z_reals) >= 2:
            z0, z1 = complex(z_reals.pop()), complex(z_reals.pop())
        else:
            z0, z1 = complex(-1.0), complex(-1.0)

        b0 = 1.0
        b1 = -(z0 + z1).real
        b2 = (z0 * z1).real
        a0 = 1.0
        a1 = -(p0 + p1)
        a2 = p0 * p1
        sections.append([b0, b1, b2, a0, a1, a2])

    # Single remaining real pole (odd order)
    if p_reals_left:
        p0 = p_reals_left.pop()
        z0 = z_reals.pop() if z_reals else -1.0
        sections.append([1.0, -z0, 0.0, 1.0, -p0, 0.0])

    sos = np.array(sections, dtype=float)

    # Distribute gain to first section
    if len(sos) > 0:
        sos[0, :3] *= k

    return sos


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
    # Step 1: Get analog prototype (passband edge at omega=1)
    za, pa, ka = elliptic_filter(N, Rp, Rs)

    # Step 2: Pre-warp cutoff frequency
    # The bilinear transform warps frequencies; pre-warping ensures the
    # digital filter's -Rp dB point lands exactly at fc.
    warped = 2.0 * fs * math.tan(math.pi * fc / fs)

    # Step 3: Frequency-scale the analog prototype from omega=1 to warped
    # H_scaled(s) = H_proto(s/warped)
    # New zeros/poles: multiply by warped
    # Gain: multiply by warped^(Np - Nz)
    za_s = za * warped
    pa_s = pa * warped
    deg_diff = len(pa_s) - len(za_s)
    ka_s = ka * (warped ** deg_diff)

    # Step 4: Bilinear transform s -> 2*fs*(z-1)/(z+1)
    # Inverse mapping: z = (2*fs + s) / (2*fs - s)
    fs2 = 2.0 * fs
    zd = (fs2 + za_s) / (fs2 - za_s)
    pd = (fs2 + pa_s) / (fs2 - pa_s)

    # Digital gain from bilinear substitution:
    # k_d = k_analog * prod(2*fs - za_i) / prod(2*fs - pa_i)
    kd = np.real(ka_s * np.prod(fs2 - za_s) / np.prod(fs2 - pa_s))

    # Add extra zeros at z = -1 (from the degree difference)
    zd = np.concatenate([zd, -np.ones(deg_diff)])

    # Step 5: Convert ZPK to cascaded second-order sections
    sos = _zpk2sos(zd, pd, kd)

    return sos
