"""
Solution: Complete elliptic filter design pipeline using Landen transformations.
Writes /app/elliptic_filter.py
"""


SOLUTION_CODE = r'''
"""
Elliptic (Cauer) filter design pipeline implemented from scratch
using Landen transformations for all elliptic function evaluations.

Based on the theory from Zavalishin, "The Art of VA Filter Design", Ch. 9.
"""

import numpy as np
import cmath
import math

LANDEN_STEPS = 50


def complete_elliptic_K(k):
    """Complete elliptic integral of the first kind K(k).

    Uses descending Landen transformation for general k.
    For k very close to 1, uses the logarithmic asymptotic expansion.
    """
    if abs(k) < 1e-18:
        return math.pi / 2.0
    if k >= 1.0:
        return float('inf')

    # For k close to 1, use the asymptotic expansion
    # K(k) = sum of terms involving ln(4/k') where k' = sqrt(1-k^2)
    kp2 = 1.0 - k * k  # k'^2
    if kp2 < 1e-6:
        kp = math.sqrt(kp2)
        L = math.log(4.0 / kp)
        # Series: K = L + (kp2/4)*(L-1) + (9*kp2^2/64)*(L-7/6) + (25*kp2^3/256)*(L-37/30) + ...
        t = kp2 / 4.0
        K_val = L
        K_val += t * (L - 1.0)
        t *= kp2 * 9.0 / 16.0
        K_val += t * (L - 7.0/6.0)
        t *= kp2 * 25.0 / 36.0
        K_val += t * (L - 37.0/30.0)
        t *= kp2 * 49.0 / 64.0
        K_val += t * (L - 533.0/420.0)
        return K_val

    K_val = math.pi / 2.0
    kn = float(k)
    for _ in range(LANDEN_STEPS):
        kp = math.sqrt(1.0 - kn * kn)
        kn = (kn / (1.0 + kp)) ** 2
        K_val *= (1.0 + kn)
        if kn < 1e-18:
            break
    return K_val


def _landen_descend(k):
    """Build descending Landen sequence: [k_0, k_{-1}, k_{-2}, ...]."""
    seq = [float(k)]
    kn = float(k)
    for _ in range(LANDEN_STEPS):
        kp = math.sqrt(1.0 - kn * kn)
        kn = (kn / (1.0 + kp)) ** 2
        seq.append(kn)
        if kn < 1e-18:
            break
    return seq


def cd(x, k):
    """Jacobian elliptic cosine cd(x, k). Supports complex x.

    Algorithm (Zavalishin Sec. 9.11):
    1. Normalize: u = x / K(k)
    2. Descend Landen to k_{-n} ~ 0 where cd -> cos
    3. At bottom: cd_{-n}(u) ~ cos(pi*u/2)
    4. Ascend: cd at k_{i-1} = (1 + k_i) * cd_at_k_i / (1 + k_i * cd_at_k_i^2)
       Using k_seq[i] to go from cd at k_seq[i] to cd at k_seq[i-1]
    """
    if abs(k) < 1e-18:
        return complex(cmath.cos(x))

    K_val = complete_elliptic_K(k)
    u = complex(x) / K_val
    k_seq = _landen_descend(k)

    # Bottom approximation: cd at tiny k ~ cos
    val = cmath.cos(cmath.pi * u / 2.0)

    # Ascending recursion: use k_seq[i] to produce cd at k_seq[i-1]
    # Loop from bottom (largest index) to index 1 (to get cd at k_seq[0] = k)
    for i in range(len(k_seq) - 1, 0, -1):
        kn = k_seq[i]
        val = (1.0 + kn) * val / (1.0 + kn * val * val)

    if isinstance(x, (int, float)) and abs(val.imag) < 1e-14:
        return val.real
    return val


def sn(x, k):
    """Jacobian elliptic sine sn(x, k). Uses sn(x) = cd(K - x)."""
    K_val = complete_elliptic_K(k)
    return cd(K_val - complex(x), k)


def cd_inv(y, k):
    """Inverse Jacobian elliptic cosine: x = cd^{-1}(y, k).

    Uses Zavalishin's descending recursion (Sec. 9.11, p.380):
      y_{new} = (2 / (1 + k_next)) * y / (1 + sqrt(1 - k^2 * y^2))
    where k is current (larger) modulus, k_next is descended (smaller).
    At bottom: u = (2/pi) * arccos(y_bottom), then x = K * u.
    """
    if abs(k) < 1e-18:
        return complex(cmath.acos(complex(y)))

    k_seq = _landen_descend(k)

    Kbypi2 = 1.0
    yn = complex(y)

    for i in range(len(k_seq) - 1):
        ki = k_seq[i]        # current (larger) modulus
        ki_next = k_seq[i+1] # descended (smaller) modulus
        sq = cmath.sqrt(1.0 - ki * ki * yn * yn)
        yn = 2.0 * yn / ((1.0 + ki_next) * (1.0 + sq))
        Kbypi2 *= (1.0 + ki_next)

    K_val = Kbypi2 * math.pi / 2.0
    u_norm = cmath.acos(yn) * 2.0 / cmath.pi
    x_val = K_val * u_norm

    if isinstance(y, (int, float)) and abs(x_val.imag) < 1e-12:
        return x_val.real
    return x_val


def sn_inv(y, k):
    """Inverse Jacobian elliptic sine: x = sn^{-1}(y, k).
    Uses sn(x) = cd(K - x) => sn_inv(y) = K - cd_inv(y).
    """
    K_val = complete_elliptic_K(k)
    return K_val - cd_inv(y, k)


def elliptic_rational(x, N, k):
    """Elliptic rational function R_N(x) of degree N with modulus k.

    Factored form (Zavalishin eq. 9.134):
      R_N(x) = x^{N&1} * prod_{z_n>0} [(1-k^2*z_n^2)/(1-z_n^2)] * (x^2-z_n^2)/(1-k^2*z_n^2*x^2)
    Zeros: z_n = cd(K*(2n+1)/N, k).
    """
    K_val = complete_elliptic_K(k)

    zeros = []
    for n in range(N):
        u = (2 * n + 1.0) / N
        zn = cd(K_val * u, k)
        if isinstance(zn, complex):
            zn = zn.real
        zeros.append(zn)

    positive_zeros = sorted([z for z in zeros if z > 1e-15])

    val = complex(x) if isinstance(x, complex) else float(x)

    if N % 2 == 1:
        product = val  # factor for the zero at origin
    else:
        product = 1.0

    for zn in positive_zeros:
        k2z2 = k * k * zn * zn
        norm = (1.0 - k2z2) / (1.0 - zn * zn)
        factor = norm * (val * val - zn * zn) / (1.0 - k2z2 * val * val)
        product *= factor

    if isinstance(product, complex) and abs(product.imag) < 1e-14:
        return product.real
    return product


def solve_degree_equation(N, k):
    """Solve: K'(k_tilde)/K(k_tilde) = N * K'(k)/K(k) for k_tilde.

    Uses bisection on the monotonically decreasing function K'/K.
    """
    kp = math.sqrt(1.0 - k * k)
    K_k = complete_elliptic_K(k)
    Kp_k = complete_elliptic_K(kp)
    target = N * Kp_k / K_k

    lo, hi = 1e-20, 1.0 - 1e-15
    for _ in range(200):
        mid = (lo + hi) / 2.0
        kp_mid = math.sqrt(1.0 - mid * mid)
        ratio = complete_elliptic_K(kp_mid) / complete_elliptic_K(mid)
        if ratio > target:
            lo = mid
        else:
            hi = mid
        if abs(hi - lo) / (abs(mid) + 1e-30) < 1e-16:
            break
    return (lo + hi) / 2.0


def _elliptic_K_from_complementary(mp):
    """Compute K(k) where k'^2 = mp (the complementary parameter).

    Uses logarithmic expansion directly from mp, avoiding 1-k^2 cancellation.
    K(k) = ln(4/k') + (k'^2/4)(ln(4/k')-1) + (9k'^4/64)(ln(4/k')-7/6) + ...
    """
    if mp < 1e-30:
        return float('inf')
    kp = math.sqrt(mp)
    L = math.log(4.0 / kp)
    K_val = L
    t = mp / 4.0
    K_val += t * (L - 1.0)
    t *= mp * 9.0 / 16.0
    K_val += t * (L - 7.0/6.0)
    t *= mp * 25.0 / 36.0
    K_val += t * (L - 37.0/30.0)
    t *= mp * 49.0 / 64.0
    K_val += t * (L - 533.0/420.0)
    t *= mp * 81.0 / 100.0
    K_val += t * (L - 1627.0/1260.0)
    return K_val


def _solve_degree_nome(N, m1):
    """Solve degree equation using nomes (matches scipy's _ellipdeg).

    Given N and m1 = k1^2, solve for m = k^2 such that:
      N * K(m) / K'(m) = K(m1) / K'(m1)

    Uses the nome q: q = exp(-pi * K'/K).
    The N-th degree transform maps q1 -> q = q1^(1/N).
    Then m = 16*q * (sum q^(n(n+1)) / (1 + 2*sum q^(n^2)))^4
    """
    K1 = complete_elliptic_K(math.sqrt(m1))
    # Use complementary formula for K' to avoid cancellation when m1 is tiny
    K1p = _elliptic_K_from_complementary(m1)

    q1 = math.exp(-math.pi * K1p / K1)
    q = q1 ** (1.0 / N)

    MMAX = 10
    num = sum(q ** (n * (n + 1)) for n in range(MMAX + 1))
    den = 1.0 + 2.0 * sum(q ** ((n + 1) ** 2) for n in range(MMAX + 1))

    return 16.0 * q * (num / den) ** 4


def _solve_k_from_ratio(target_ratio):
    """Find k such that K'(k)/K(k) = target_ratio."""
    lo, hi = 1e-20, 1.0 - 1e-15
    for _ in range(200):
        mid = (lo + hi) / 2.0
        kp_mid = math.sqrt(1.0 - mid * mid)
        ratio = complete_elliptic_K(kp_mid) / complete_elliptic_K(mid)
        if ratio > target_ratio:
            lo = mid
        else:
            hi = mid
        if abs(hi - lo) / (abs(mid) + 1e-30) < 1e-16:
            break
    return (lo + hi) / 2.0


def elliptic_filter_poles_zeros(N, Rp, Rs):
    """Design an analog lowpass elliptic filter.

    Parameters
    ----------
    N : int - Filter order
    Rp : float - Passband ripple (dB)
    Rs : float - Stopband attenuation (dB)

    Returns
    -------
    zeros, poles, gain matching scipy.signal.ellip(N, Rp, Rs, 1.0, analog=True, output='zpk')
    """
    eps = math.sqrt(10.0 ** (Rp / 10.0) - 1.0)
    eps_s = math.sqrt(10.0 ** (Rs / 10.0) - 1.0)
    k1 = eps / eps_s  # discrimination parameter

    # Find selectivity m = k^2 using nome-based degree equation (matches scipy)
    kp1 = math.sqrt(1.0 - k1 * k1)
    m1 = k1 * k1  # = ck1_sq in scipy
    m = _solve_degree_nome(N, m1)
    k = math.sqrt(m)

    K_val = complete_elliptic_K(k)
    kp = math.sqrt(1.0 - k * k)
    Kp_val = complete_elliptic_K(kp)

    # Filter zeros: use sn-based approach matching scipy
    # scipy uses j = arange(1 - N%2, N, 2), computes sn(j*K/N, m)
    # zeros at 1/(sqrt(m) * sn_val) for nonzero sn
    j_indices = list(range(1 - N % 2, N, 2))
    sn_vals = []
    for ji in j_indices:
        s_val = sn(ji * K_val / N, k)
        if isinstance(s_val, complex):
            s_val = s_val.real
        sn_vals.append(s_val)

    filter_zeros = []
    for sv in sn_vals:
        if abs(sv) > 1e-15:
            omega = 1.0 / (k * abs(sv))
            filter_zeros.append(1j * omega)
            filter_zeros.append(-1j * omega)

    # Compute v0: pole depth parameter
    # v0 = K * r / (N * K(k1)) where r = sc_inv(1/eps, kp1)
    # sc_inv(1/eps, kp1) = sn_inv(imaginary via Landen)
    # Actually: _arc_jac_sc1(1/eps, m1) from scipy
    # = Im(sn_inv(j/eps, k1)) where sn_inv uses modulus k1
    # We use: sc(x, kp1) = 1/eps => x = sc_inv(1/eps, kp1)
    # sc_inv(y, m) = sn_inv(y/sqrt(1+y^2), m)
    sin_phi = 1.0 / math.sqrt(1.0 + eps * eps)
    Kp1_val = complete_elliptic_K(kp1)

    # sc_inv(1/eps, kp1) via sn_inv
    # sn(jx, k1) = j*sc(x, k1') => sn_inv(j/eps, k1) = j*sc_inv(1/eps, kp1)
    # So sc_inv(1/eps, kp1) = Im(sn_inv(j/eps, k1)) / j = sn_inv(j/eps, k1) / j
    # But sn_inv of complex argument is tricky. Use the direct formula instead:
    # sc_inv(1/eps, kp1) = sn_inv(sin_phi, kp1) where sin_phi = 1/sqrt(1+eps^2)
    sn_inv_val = sn_inv(sin_phi, kp1)
    v0 = K_val * sn_inv_val / (N * complete_elliptic_K(k1))

    # Poles using explicit real-argument formula (matches scipy exactly):
    # p_i = -(c_i*d_i*sv*cv + j*s_i*dv) / (1 - (d_i*sv)^2)
    # where s_i, c_i, d_i = sn, cn, dn at j_i*K/N with modulus k
    # and sv, cv, dv = sn, cn, dn at v0 with modulus kp = sqrt(1-k^2)

    sv = sn(v0, kp)
    cv = cd(complete_elliptic_K(kp) - v0, kp)  # cn = cd(K-x) ... wait, sn(K-x) = cd(x)
    # Actually: cn(x) = cd(K-x) is wrong. cn(x, k) != cd(K-x, k).
    # cn(x) = sqrt(1 - sn^2(x))
    sv_val = sv if isinstance(sv, float) else sv.real
    cv_val = math.sqrt(1.0 - sv_val * sv_val)  # cn(v0, kp) = sqrt(1 - sn^2(v0, kp))
    dv_val = math.sqrt(1.0 - kp * kp * sv_val * sv_val)  # dn(v0, kp)

    half_poles = []
    for ji in j_indices:
        x = ji * K_val / N
        si = sn(x, k)
        if isinstance(si, complex):
            si = si.real
        ci = math.sqrt(1.0 - si * si)
        di = math.sqrt(1.0 - k * k * si * si)

        numer = -(ci * di * sv_val * cv_val + 1j * si * dv_val)
        denom = 1.0 - (di * sv_val) ** 2
        p = numer / denom
        half_poles.append(p)

    # Build full pole set
    final_poles = []
    for p in half_poles:
        if abs(p.imag) < 1e-14 * abs(p):
            final_poles.append(complex(p.real, 0.0))
        else:
            final_poles.append(p)

    if N % 2 == 1:
        # Odd: take conjugates of complex poles only
        conj_poles = [np.conj(p) for p in final_poles if abs(p.imag) > 1e-14 * abs(p)]
        final_poles = final_poles + conj_poles
    else:
        # Even: all poles come with conjugates
        conj_poles = [np.conj(p) for p in final_poles]
        final_poles = final_poles + conj_poles

    final_poles.sort(key=lambda p: abs(p.imag))
    filter_zeros.sort(key=lambda z: abs(z.imag))

    z_arr = np.array(filter_zeros, dtype=complex)
    p_arr = np.array(final_poles, dtype=complex)

    # Gain: H(0) = 1 (odd N) or 1/sqrt(1+eps^2) (even N)
    num_at_0 = np.prod(-z_arr) if len(z_arr) > 0 else 1.0
    den_at_0 = np.prod(-p_arr)
    target_H0 = 1.0 if N % 2 == 1 else 1.0 / math.sqrt(1.0 + eps * eps)
    gain = float(abs(target_H0 * den_at_0 / num_at_0))

    return z_arr, p_arr, gain


if __name__ == "__main__":
    z, p, k = elliptic_filter_poles_zeros(5, 1.0, 40.0)
    print(f"Order 5, Rp=1dB, Rs=40dB:")
    print(f"  Zeros: {z}")
    print(f"  Poles: {p}")
    print(f"  Gain:  {k}")
'''

with open("/app/elliptic_filter.py", "w") as f:
    f.write(SOLUTION_CODE)

print("Solution written to /app/elliptic_filter.py")
