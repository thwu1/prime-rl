
"""
Build the elliptic filter design module at /app/elliptic_filter.py.
Implements the full pipeline from Landen transformations through
Jacobian elliptic functions to elliptic (Cauer) filter pole/zero computation.

Based on the mathematical framework from Zavalishin's "The Art of VA Filter Design",
Chapter 9 on classical signal processing filters.
"""

SOLUTION_CODE = r'''

"""
Elliptic (Cauer) filter design from first principles using Landen transformations.

No scipy.signal dependency — only numpy for basic array/complex math.
"""

import numpy as np


# ============================================================
# 1. Landen Sequence
# ============================================================

def landen_sequence(k, n=7):
    """Compute descending Landen sequence of elliptic moduli.

    The descending Landen transformation:
        k_next = (k / (1 + k'))^2  where k' = sqrt(1 - k^2)
    This reduces k toward 0, making elliptic functions approach trigonometric ones.

    Parameters
    ----------
    k : float
        Starting elliptic modulus, 0 < k < 1.
    n : int
        Number of iterations (sequence length including k itself).

    Returns
    -------
    list of float
        [k_0, k_{-1}, k_{-2}, ...] with k_0 = k, each smaller than previous.
    """
    seq = [float(k)]
    ki = float(k)
    for _ in range(n - 1):
        kp = np.sqrt(1.0 - ki * ki)
        ki = (ki / (1.0 + kp)) ** 2
        seq.append(ki)
        if ki < 1e-18:
            break
    return seq


# ============================================================
# 2. Complete Elliptic Integral K(k)
# ============================================================

def complete_elliptic_K(k):
    """Compute the complete elliptic integral of the first kind K(k).

    Uses the ascending product formula from Landen transformations:
        K(k) = (pi/2) * prod_{i=1}^{n} (1 + k_{-i})

    Parameters
    ----------
    k : float
        Elliptic modulus, 0 <= k < 1.

    Returns
    -------
    float
        K(k).
    """
    k = float(k)
    if k < 1e-15:
        return np.pi / 2.0
    if k > 1.0 - 1e-15:
        return 1e15  # K(1) = infinity

    seq = landen_sequence(k, n=30)
    K = np.pi / 2.0
    for i in range(1, len(seq)):
        K *= (1.0 + seq[i])
    return K


# ============================================================
# 3. Jacobian Elliptic Function cd(u, k)
# ============================================================

def elliptic_cd(u, k):
    """Evaluate the Jacobian elliptic function cd(u, k) = cn(u,k)/dn(u,k).

    Uses ascending Landen recursion from the bottom of the Landen sequence:
        cd_{n+1}(x) = (1 + k_n) * cd_n(x) / (1 + k_n * cd_n(x)^2)

    At small modulus k_{-M} ~ 0, cd(u, k_{-M}) ~ cos(u) since K ~ pi/2.

    Parameters
    ----------
    u : complex or float
        Argument (NOT normalized by K).
    k : float
        Elliptic modulus, 0 < k < 1.

    Returns
    -------
    complex
        cd(u, k).
    """
    u = complex(u)
    k = float(k)

    if k < 1e-15:
        return np.cos(u)

    # Build descending Landen sequence
    seq = landen_sequence(k, n=30)

    # Compute K(k) for normalizing the argument
    K = complete_elliptic_K(k)

    # Normalized argument: x = u / K(k)
    # At the bottom of the Landen sequence, cd_{-M}(x) ~ cos(pi*x/2)
    x = u / K
    w = np.cos(np.pi * x / 2.0)

    # Ascending Landen recursion (9.102b):
    # cd_{n+1}(x) = (1 + k_n) * cd_n(x) / (1 + k_n * cd_n(x)^2)
    # where k_n is the LOWER (source) modulus and k_{n+1} = L(k_n) is higher.
    # In our descending sequence, seq[i+1] is the source modulus for step i.
    for i in range(len(seq) - 2, -1, -1):
        ki = seq[i + 1]  # k_n: the source (lower) modulus
        w = (1.0 + ki) * w / (1.0 + ki * w * w)

    return w


# ============================================================
# 4. Jacobian sn, cn, dn from cd
# ============================================================

def _sn(u, k):
    """sn(u, k) = cd(u - K(k), k)."""
    K = complete_elliptic_K(k)
    return elliptic_cd(u - K, k)


def _cn_dn(u, k):
    """Compute cn(u,k) and dn(u,k) from cd and sn.

    Uses: cd = cn/dn and dn^2 = 1 - k^2*sn^2.
    """
    s = _sn(u, k)
    c_over_d = elliptic_cd(u, k)  # cd = cn/dn
    dn2 = 1.0 - k**2 * s**2
    dn = np.sqrt(dn2)
    cn = c_over_d * dn
    return cn, dn


def _sc(u, k):
    """sc(u, k) = sn(u,k) / cn(u,k)."""
    s = _sn(u, k)
    cn, _ = _cn_dn(u, k)
    if abs(cn) < 1e-30:
        return complex(1e15) * np.sign(np.real(s))
    return s / cn


# ============================================================
# 5. Inverse Jacobian Elliptic Function cd^{-1}(w, k)
# ============================================================

def elliptic_cd_inv(w, k):
    """Compute cd^{-1}(w, k) — the inverse of the Jacobian elliptic cosine.

    Uses Newton-Raphson iteration on cd(u, k) - w = 0.

    Parameters
    ----------
    w : complex or float
        Target value.
    k : float
        Elliptic modulus, 0 < k < 1.

    Returns
    -------
    complex
        u such that cd(u, k) = w, in the principal domain.
    """
    w = complex(w)
    k = float(k)

    if k < 1e-15:
        return np.arccos(w)

    K = complete_elliptic_K(k)
    kp = np.sqrt(1.0 - k * k)
    Kp = complete_elliptic_K(kp)

    # Initial guess based on the acos of w scaled by K/(pi/2)
    w_r = np.real(w)
    w_i = np.imag(w)

    if abs(w_i) < 1e-12 and -1.0 <= w_r <= 1.0:
        # w is real in [-1, 1]: u is real in [0, 2K]
        u = np.arccos(w_r) * (2 * K / np.pi)
    elif abs(w_i) < 1e-12 and w_r > 1.0:
        # w real > 1: u is purely imaginary, from cd(jv, k) = 1/dn(v, k') >= 1
        # Use acosh-based estimate
        val = min(w_r, 1.0 / k - 1e-10)
        u = 1j * np.arccosh(val) * (Kp / (np.pi / 2.0))
    elif abs(w_i) < 1e-12 and w_r < -1.0:
        # w real < -1: u near 2K + imaginary shift
        val = min(-w_r, 1.0 / k - 1e-10)
        u = 2 * K + 1j * np.arccosh(val) * (Kp / (np.pi / 2.0))
    else:
        # General complex case
        u = np.arccos(w) * (2 * K / np.pi)

    # Newton-Raphson refinement
    delta = K * 1e-8
    for iteration in range(150):
        f_val = elliptic_cd(u, k) - w
        if abs(f_val) < 1e-14:
            break
        # Numerical derivative
        df = (elliptic_cd(u + delta, k) - elliptic_cd(u - delta, k)) / (2 * delta)
        if abs(df) < 1e-30:
            # Try a different delta
            delta *= 10
            continue
        step = f_val / df
        u = u - step

    return u


# ============================================================
# 6. Degree Equation Solver
# ============================================================

def _solve_degree_equation_for_k(N, k1):
    """Solve the degree equation for k (selectivity) given k1 (discrimination).

    The degree equation: K'(k)/K(k) = (1/N) * K'(k1)/K(k1)

    As k increases from 0 to 1, K'(k)/K(k) decreases from infinity to 0.

    Parameters
    ----------
    N : int
        Filter order.
    k1 : float
        Discrimination parameter (epsilon_p / epsilon_s).

    Returns
    -------
    float
        k satisfying the degree equation.
    """
    k1p = np.sqrt(1.0 - k1 * k1)
    K_k1 = complete_elliptic_K(k1)
    K_k1p = complete_elliptic_K(k1p)
    target = K_k1p / (N * K_k1)  # = K'(k)/K(k)

    # Bisection: find k such that K(kp)/K(k) = target
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


def _solve_degree_equation(N, k):
    """Solve the degree equation for k_tilde given k (selectivity).

    K'(k_tilde)/K(k_tilde) = N * K'(k)/K(k)

    As k_tilde decreases from 1 to 0, K'/K increases from 0 to infinity.

    Parameters
    ----------
    N : int
        Filter order.
    k : float
        Selectivity parameter.

    Returns
    -------
    float
        k_tilde satisfying the degree equation.
    """
    kp = np.sqrt(1.0 - k * k)
    K_val = complete_elliptic_K(k)
    Kp_val = complete_elliptic_K(kp)
    target = N * Kp_val / K_val

    lo, hi = 1e-18, 1.0 - 1e-15
    for _ in range(200):
        mid = (lo + hi) / 2.0
        midp = np.sqrt(1.0 - mid * mid)
        K_mid = complete_elliptic_K(mid)
        Kp_mid = complete_elliptic_K(midp)
        ratio = Kp_mid / K_mid
        if ratio < target:
            hi = mid
        else:
            lo = mid
        if abs(ratio - target) / (abs(target) + 1e-30) < 1e-14:
            break
    return (lo + hi) / 2.0


# ============================================================
# 7. Elliptic Rational Function R_N(x)
# ============================================================

def elliptic_rational_function(x, N, k):
    """Evaluate the N-th order elliptic rational function R_N(x).

    R_N(x) = cd(N * (K_tilde/K) * cd^{-1}(x, k), k_tilde)

    where K = K(k), K_tilde = K(k_tilde), and k_tilde satisfies
    the degree equation K'(k_tilde)/K(k_tilde) = N * K'(k)/K(k).

    Parameters
    ----------
    x : complex or float
        Argument.
    N : int
        Order.
    k : float
        Elliptic modulus (selectivity parameter).

    Returns
    -------
    complex
        R_N(x).
    """
    x = complex(x)
    k_tilde = _solve_degree_equation(N, k)

    K_val = complete_elliptic_K(k)
    K_tilde = complete_elliptic_K(k_tilde)

    u = elliptic_cd_inv(x, k)
    v = N * (K_tilde / K_val) * u
    return elliptic_cd(v, k_tilde)


# ============================================================
# 8. Elliptic Lowpass Filter Design
# ============================================================

def design_elliptic_lowpass(N, ripple_db, stopband_db, omega_s=None):
    """Design an N-th order elliptic (Cauer) lowpass filter.

    Computes the analog prototype with passband edge at 1 rad/s.

    Parameters
    ----------
    N : int
        Filter order.
    ripple_db : float
        Passband ripple in dB.
    stopband_db : float
        Minimum stopband attenuation in dB.
    omega_s : float, optional
        Stopband edge frequency (computed from degree equation if not given).

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

    # Discrimination parameter
    k1 = epsilon_p / epsilon_s
    k1p = np.sqrt(1.0 - k1 * k1)

    # Solve degree equation for selectivity k
    k = _solve_degree_equation_for_k(N, k1)
    kp = np.sqrt(1.0 - k * k)

    K = complete_elliptic_K(k)
    Kp = complete_elliptic_K(kp)
    K1 = complete_elliptic_K(k1)
    K1p = complete_elliptic_K(k1p)

    # ================================================================
    # ZEROS: on the imaginary axis
    # Transfer function zeros are at the poles of R_N(omega).
    # Poles of R_N occur at omega = 1/(k * cd((2m+1)*K/N, k))
    # for m = 0, 1, ..., floor(N/2) - 1
    # ================================================================
    L = N // 2  # number of zero pairs
    zeros_s = []
    for m in range(L):
        u_m = (2 * m + 1) * K / N
        cd_val = np.real(elliptic_cd(u_m, k))
        omega_z = 1.0 / (k * cd_val)
        zeros_s.append(1j * omega_z)
        zeros_s.append(-1j * omega_z)

    # ================================================================
    # POLES: complex values from elliptic cd with imaginary shift
    # sigma = w0 * K / (N * K1)
    # where w0 satisfies sc(w0, k1') = 1/epsilon_p
    # Poles: s_n = j * cd((2n+1)*K/N - j*sigma, k)  for n = 0, ..., N-1
    # ================================================================

    # Find w0 by bisection: sc(w0, k1') = 1/epsilon_p
    target_sc = 1.0 / epsilon_p
    K_k1p = K1p

    # sc(w, k1p) is monotonically increasing from 0 at w=0 to infinity at w=K(k1p)
    w_lo, w_hi = 1e-15, K_k1p * (1.0 - 1e-10)
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

    # Imaginary shift in the u-domain
    sigma = w0 * K / (N * K1)

    # Compute all N poles
    poles = []
    for n in range(N):
        u_n = (2 * n + 1) * K / N
        omega_n = elliptic_cd(complex(u_n, -sigma), k)
        s_n = 1j * omega_n
        poles.append(s_n)

    # All poles should be in the left half-plane (Re(s) < 0)
    # Enforce conjugate pairing: pole n pairs with pole N-1-n
    final_poles = []
    for n in range(N):
        m = N - 1 - n
        if n < m:
            # Conjugate pair
            p = poles[n]
            final_poles.append(p)
            final_poles.append(np.conj(p))
        elif n == m:
            # Real pole (odd N only)
            p = poles[n]
            final_poles.append(complex(np.real(p), 0.0))

    poles = np.array(final_poles)
    zeros = np.array(zeros_s) if zeros_s else np.array([], dtype=complex)

    # ================================================================
    # GAIN
    # H(0) = 1/sqrt(1 + eps^2 * R_N(0)^2)
    # R_N(0) = 0 for odd N, (-1)^{N/2} for even N
    # ================================================================
    if N % 2 == 1:
        H0 = 1.0
    else:
        H0 = 1.0 / np.sqrt(1.0 + epsilon_p ** 2)

    # H(s) = gain * prod(s - z_i) / prod(s - p_j)
    # H(0) = gain * prod(-z_i) / prod(-p_j)
    prod_neg_z = np.prod(-zeros) if len(zeros) > 0 else 1.0
    prod_neg_p = np.prod(-poles)

    gain = np.real(H0 * prod_neg_p / prod_neg_z)
    gain = abs(gain)

    return zeros, poles, gain
'''

with open("/app/elliptic_filter.py", "w") as f:
    f.write(SOLUTION_CODE)

print("Solution written to /app/elliptic_filter.py")
print()

# Quick verification
import sys
sys.path.insert(0, "/app")

# Reimport with fresh module
if "elliptic_filter" in sys.modules:
    del sys.modules["elliptic_filter"]

from elliptic_filter import (
    complete_elliptic_K,
    landen_sequence,
    elliptic_cd,
    design_elliptic_lowpass,
)
import numpy as np

# Test K(k)
print("=== K(k) tests ===")
from scipy.special import ellipk
for k_test in [0.1, 0.5, 0.9, 0.99]:
    ours = complete_elliptic_K(k_test)
    ref = ellipk(k_test**2)
    print(f"  k={k_test}: ours={ours:.10f}, scipy={ref:.10f}, err={abs(ours-ref):.2e}")

# Test cd(u, k)
print("\n=== cd(u,k) tests ===")
from scipy.special import ellipj
k_test = 0.7
K_test = complete_elliptic_K(k_test)
for frac in [0.1, 0.5, 0.9]:
    u = frac * K_test
    sn, cn, dn, _ = ellipj(u, k_test**2)
    cd_ref = cn / dn
    cd_ours = elliptic_cd(u, k_test)
    print(f"  u={frac}*K: ours={cd_ours:.10f}, ref={cd_ref:.10f}, err={abs(cd_ours-cd_ref):.2e}")

# Test filter design
print("\n=== Filter design test ===")
from scipy.signal import ellip
z_ref, p_ref, k_ref = ellip(5, 1.0, 60.0, 1.0, btype='low', analog=True, output='zpk')
print(f"scipy: {len(z_ref)} zeros, {len(p_ref)} poles, gain={k_ref:.8f}")
print(f"  poles: {np.sort_complex(p_ref)}")
print(f"  zeros: {np.sort_complex(z_ref)}")

omega_s = np.min(np.abs(z_ref))
z_ours, p_ours, k_ours = design_elliptic_lowpass(5, 1.0, 60.0, omega_s)
print(f"\nours:  {len(z_ours)} zeros, {len(p_ours)} poles, gain={k_ours:.8f}")
print(f"  poles: {np.sort_complex(p_ours)}")
print(f"  zeros: {np.sort_complex(z_ours)}")
