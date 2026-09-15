#!/usr/bin/env python3

"""
Fix all bugs in the elliptic filter design pipeline.

Six issues across four layers:

1. Makefile: builds static archive (.a) instead of shared library (.so),
   and is missing -lm for math library linkage.
   Fix: change target to .so, use gcc -shared, add -lm.

2. native_binding.py: CmplxResult ctypes struct has fields in wrong
   order (imag, real) vs the C struct (real, imag), silently swapping
   real and imaginary components.
   Fix: swap field order to match C struct layout.

3. libelliptic.c K(k): product loop starts at i=0 instead of i=1,
   including an extraneous factor of (1+k) in the product.
   Fix: change loop start from 0 to 1.

4. libelliptic.c cd(): ascending Landen recursion denominator uses
   ki*w_re and ki*w_im (linear in w) instead of the correct
   ki*ww_re and ki*ww_im (quadratic: w*w).
   Fix: compute w*w as complex square, use in denominator.

5. cd_inverse.py: transition band initial guesses for |w|>1 are
   missing the imaginary unit 1j before np.arccosh, placing
   Newton-Raphson in the wrong region of the complex plane.
   Fix: add 1j multiplier in both branches.

6. filter_design.py: sigma formula uses K(k1') = K1p instead of
   K(k1) = K1, displacing poles incorrectly.
   Fix: change K1p to K1 in the sigma computation.
"""

import os
import subprocess


def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)


# ================================================================
# Fix 1: Makefile
# ================================================================
write_file("/app/Makefile", """\
CC = gcc
CFLAGS = -O2 -fPIC -Wall

all: libelliptic.so

libelliptic.so: libelliptic.c libelliptic.h
\t$(CC) $(CFLAGS) -shared $< -o $@ -lm

clean:
\trm -f *.o *.a *.so
""")

# ================================================================
# Fix 2: native_binding.py (swap CmplxResult fields)
# ================================================================
write_file("/app/native_binding.py", '''\
"""ctypes bindings for the libelliptic native shared library."""

import ctypes
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_dir, "libelliptic.so"))


class LandenResult(ctypes.Structure):
    """Mirrors the C LandenResult struct."""
    _fields_ = [
        ("values", ctypes.c_double * 30),
        ("length", ctypes.c_int),
    ]


class CmplxResult(ctypes.Structure):
    """Mirrors the C CmplxResult struct."""
    _fields_ = [
        ("real", ctypes.c_double),
        ("imag", ctypes.c_double),
    ]


_lib.landen_sequence_c.argtypes = [ctypes.c_double, ctypes.c_int]
_lib.landen_sequence_c.restype = LandenResult

_lib.complete_elliptic_K_c.argtypes = [ctypes.c_double]
_lib.complete_elliptic_K_c.restype = ctypes.c_double

_lib.elliptic_cd_c.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
_lib.elliptic_cd_c.restype = CmplxResult


def landen_sequence(k, n=7):
    """Compute descending Landen sequence via native C library."""
    result = _lib.landen_sequence_c(float(k), int(n))
    return [result.values[i] for i in range(result.length)]


def complete_elliptic_K(k):
    """Compute K(k) via native C library."""
    return _lib.complete_elliptic_K_c(float(k))


def elliptic_cd(u, k):
    """Evaluate cd(u, k) via native C library."""
    u = complex(u)
    result = _lib.elliptic_cd_c(u.real, u.imag, float(k))
    return complex(result.real, result.imag)
''')

# ================================================================
# Fix 3 & 4: libelliptic.c (K product loop + cd denominator)
# ================================================================
write_file("/app/libelliptic.c", r'''

#include <math.h>
#include <string.h>
#include "libelliptic.h"

LandenResult landen_sequence_c(double k, int n) {
    LandenResult result;
    memset(&result, 0, sizeof(result));
    if (n > MAX_LANDEN) n = MAX_LANDEN;

    result.values[0] = k;
    result.length = 1;
    double ki = k;

    for (int i = 1; i < n; i++) {
        double kp = sqrt(1.0 - ki * ki);
        double ratio = ki / (1.0 + kp);
        ki = ratio * ratio;
        result.values[i] = ki;
        result.length = i + 1;
        if (ki < 1e-18) break;
    }
    return result;
}

/* FIX: product loop starts at i=1 (was i=0) */
double complete_elliptic_K_c(double k) {
    if (k < 1e-15) return M_PI / 2.0;
    if (k > 1.0 - 1e-15) return 1e15;

    LandenResult seq = landen_sequence_c(k, 30);
    double K = M_PI / 2.0;

    for (int i = 1; i < seq.length; i++) {
        K *= (1.0 + seq.values[i]);
    }
    return K;
}

CmplxResult elliptic_cd_c(double u_re, double u_im, double k) {
    CmplxResult result;

    if (k < 1e-15) {
        result.real = cos(u_re) * cosh(u_im);
        result.imag = -sin(u_re) * sinh(u_im);
        return result;
    }

    LandenResult seq = landen_sequence_c(k, 30);
    double K = complete_elliptic_K_c(k);

    double x_re = u_re / K;
    double x_im = u_im / K;

    double arg_re = M_PI * x_re / 2.0;
    double arg_im = M_PI * x_im / 2.0;
    double w_re = cos(arg_re) * cosh(arg_im);
    double w_im = -sin(arg_re) * sinh(arg_im);

    for (int i = seq.length - 2; i >= 0; i--) {
        double ki = seq.values[i + 1];

        /* FIX: compute w*w properly as complex square */
        double ww_re = w_re * w_re - w_im * w_im;
        double ww_im = 2.0 * w_re * w_im;

        /* Denominator uses w*w (quadratic), not w (linear) */
        double denom_re = 1.0 + ki * ww_re;
        double denom_im = ki * ww_im;

        double num_re = (1.0 + ki) * w_re;
        double num_im = (1.0 + ki) * w_im;

        double denom_mag2 = denom_re * denom_re + denom_im * denom_im;
        w_re = (num_re * denom_re + num_im * denom_im) / denom_mag2;
        w_im = (num_im * denom_re - num_re * denom_im) / denom_mag2;
    }

    result.real = w_re;
    result.imag = w_im;
    return result;
}
''')

# ================================================================
# Fix 5: cd_inverse.py (add 1j in transition band initial guesses)
# ================================================================
write_file("/app/cd_inverse.py", '''\
"""Inverse Jacobian elliptic function cd^{-1}(w, k) via Newton-Raphson."""

import numpy as np
from elliptic_k import complete_elliptic_K
from jacobi_cd import elliptic_cd


def elliptic_cd_inv(w, k):
    """Compute u such that cd(u, k) = w."""
    w = complex(w)
    k = float(k)

    if k < 1e-15:
        return np.arccos(w)

    K = complete_elliptic_K(k)
    kp = np.sqrt(1.0 - k * k)
    Kp = complete_elliptic_K(kp)

    w_r = np.real(w)
    w_i = np.imag(w)

    if abs(w_i) < 1e-12 and -1.0 <= w_r <= 1.0:
        u = np.arccos(w_r) * (2 * K / np.pi)
    elif abs(w_i) < 1e-12 and w_r > 1.0:
        val = min(w_r, 1.0 / k - 1e-10)
        u = 1j * np.arccosh(val) * (Kp / (np.pi / 2.0))
    elif abs(w_i) < 1e-12 and w_r < -1.0:
        val = min(-w_r, 1.0 / k - 1e-10)
        u = 2 * K + 1j * np.arccosh(val) * (Kp / (np.pi / 2.0))
    else:
        u = np.arccos(w) * (2 * K / np.pi)

    delta = K * 1e-8
    for iteration in range(150):
        f_val = elliptic_cd(u, k) - w
        if abs(f_val) < 1e-14:
            break
        df = (elliptic_cd(u + delta, k) - elliptic_cd(u - delta, k)) / (2 * delta)
        if abs(df) < 1e-30:
            delta *= 10
            continue
        step = f_val / df
        u = u - step

    return u
''')

# ================================================================
# Fix 6: filter_design.py (sigma uses K1 not K1p)
# ================================================================
write_file("/app/filter_design.py", '''\
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
    """Solve K\'(k)/K(k) = (1/N) * K\'(k1)/K(k1) for k (selectivity)."""
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
    """Design an N-th order analog elliptic lowpass filter prototype."""
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

    L = N // 2
    zeros_s = []
    for m in range(L):
        u_m = (2 * m + 1) * K / N
        cd_val = np.real(elliptic_cd(u_m, k))
        omega_z = 1.0 / (k * cd_val)
        zeros_s.append(1j * omega_z)
        zeros_s.append(-1j * omega_z)

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

    sigma = w0 * K / (N * K1)

    poles = []
    for n in range(N):
        u_n = (2 * n + 1) * K / N
        omega_n = elliptic_cd(complex(u_n, -sigma), k)
        s_n = 1j * omega_n
        poles.append(s_n)

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

    if N % 2 == 1:
        H0 = 1.0
    else:
        H0 = 1.0 / np.sqrt(1.0 + epsilon_p ** 2)

    prod_neg_z = np.prod(-zeros) if len(zeros) > 0 else 1.0
    prod_neg_p = np.prod(-poles)
    gain = abs(np.real(H0 * prod_neg_p / prod_neg_z))

    return zeros, poles, gain
''')

# ================================================================
# Rebuild the shared library
# ================================================================
print("Cleaning old build artifacts...")
result = subprocess.run(["make", "clean"], cwd="/app", capture_output=True, text=True)
print(result.stdout.strip())

print("Building libelliptic.so...")
result = subprocess.run(["make"], cwd="/app", capture_output=True, text=True)
if result.returncode != 0:
    print("BUILD FAILED:")
    print(result.stderr)
    raise RuntimeError("Failed to build libelliptic.so")
print(result.stdout.strip())
print("Build successful. All fixes applied.")
