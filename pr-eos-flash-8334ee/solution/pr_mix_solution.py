"""Peng-Robinson cubic EOS for multicomponent mixtures with VLE flash.


Uses a C shared library (libcubic.so) via ctypes for the cubic equation
solver, with all thermodynamic logic in pure Python.
"""

import math
import ctypes
import os

R = 8.314462618153241  # J/(mol*K) CODATA 2018

_sqrt2 = math.sqrt(2.0)
_X_PR = (
    -1.0
    + (6.0 * _sqrt2 + 8.0) ** (1.0 / 3.0)
    - (6.0 * _sqrt2 - 8.0) ** (1.0 / 3.0)
) / 3.0
OMEGA_A = 8.0 * (5.0 * _X_PR + 1.0) / (49.0 - 37.0 * _X_PR)
OMEGA_B = _X_PR / (_X_PR + 3.0)

# Load C shared library for cubic equation solving
_lib_path = '/app/libcubic/libcubic.so'
_lib = ctypes.CDLL(_lib_path)
_solve_cubic_eos = _lib.solve_cubic_eos
_solve_cubic_eos.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double * 3]
_solve_cubic_eos.restype = ctypes.c_int


def _pr_pure_a_alpha_b(Tc, Pc, omega, T):
    """Return (a*alpha(T), b) for one pure component."""
    a = OMEGA_A * R * R * Tc * Tc / Pc
    b = OMEGA_B * R * Tc / Pc
    kappa = 0.37464 + 1.54226 * omega - 0.26992 * omega * omega
    sqrtTr = math.sqrt(T / Tc)
    alpha = (1.0 + kappa * (1.0 - sqrtTr)) ** 2
    return a * alpha, b


def _mix_params(T, Tcs, Pcs, omegas, zs, kijs):
    """Compute mixture a_alpha_mix, b_mix, cross-term matrix, and pure bs."""
    N = len(zs)
    a_alphas_pure = []
    bs = []
    for i in range(N):
        aa_i, b_i = _pr_pure_a_alpha_b(Tcs[i], Pcs[i], omegas[i], T)
        a_alphas_pure.append(aa_i)
        bs.append(b_i)

    a_alpha_ijs = [[0.0] * N for _ in range(N)]
    for i in range(N):
        for j in range(i, N):
            val = math.sqrt(a_alphas_pure[i] * a_alphas_pure[j]) * (1.0 - kijs[i][j])
            a_alpha_ijs[i][j] = val
            a_alpha_ijs[j][i] = val

    a_alpha_mix = 0.0
    for i in range(N):
        for j in range(N):
            a_alpha_mix += zs[i] * zs[j] * a_alpha_ijs[i][j]

    b_mix = 0.0
    for i in range(N):
        b_mix += zs[i] * bs[i]

    return a_alpha_mix, b_mix, a_alpha_ijs, bs


def _solve_cubic_volumes(T, P, a_alpha, b):
    """Solve PR EOS cubic for molar volumes using C library; return sorted physical roots."""
    RT = R * T
    A = a_alpha * P / (RT * RT)
    B = b * P / RT

    roots_arr = (ctypes.c_double * 3)()
    count = _solve_cubic_eos(A, B, roots_arr)

    volumes = []
    for i in range(count):
        Z = roots_arr[i]
        V = Z * RT / P
        if V > b:
            volumes.append(V)

    volumes.sort()
    return volumes


def _fugacity_coefficients_from_V(T, P, V, zs, a_alpha_mix, b_mix, a_alpha_ijs, bs):
    """Compute phi_i for each component from a given molar volume root."""
    N = len(zs)
    RT = R * T
    Z = P * V / RT
    A = a_alpha_mix * P / (RT * RT)
    B = b_mix * P / RT

    log_ratio = math.log(
        (Z + (1.0 + _sqrt2) * B) / (Z + (1.0 - _sqrt2) * B)
    )
    coeff = A / (2.0 * _sqrt2 * B)

    phis = []
    for i in range(N):
        s = 0.0
        for j in range(N):
            s += zs[j] * a_alpha_ijs[i][j]
        s *= 2.0

        bi_b = bs[i] / b_mix

        ln_phi = (
            bi_b * (Z - 1.0)
            - math.log(Z - B)
            - coeff * (s / a_alpha_mix - bi_b) * log_ratio
        )
        phis.append(math.exp(ln_phi))

    return phis


def mixture_fugacity_coefficients(T, P, zs, Tcs, Pcs, omegas, kijs, phase='liquid'):
    """Return list of fugacity coefficients for each component."""
    a_alpha_mix, b_mix, a_alpha_ijs, bs = _mix_params(T, Tcs, Pcs, omegas, zs, kijs)
    volumes = _solve_cubic_volumes(T, P, a_alpha_mix, b_mix)

    if not volumes:
        raise ValueError("No physical volume root found for the given conditions")

    V = volumes[0] if phase == 'liquid' else volumes[-1]
    return _fugacity_coefficients_from_V(T, P, V, zs, a_alpha_mix, b_mix, a_alpha_ijs, bs)


def rachford_rice(zs, Ks):
    """Solve the Rachford-Rice equation for vapor fraction VF in [0, 1]."""
    N = len(zs)
    Km1 = [K - 1.0 for K in Ks]

    rr_at_0 = sum(zs[i] * Km1[i] for i in range(N))
    rr_at_1 = sum(zs[i] * Km1[i] / Ks[i] for i in range(N))

    if rr_at_0 <= 0.0:
        return 0.0
    if rr_at_1 >= 0.0:
        return 1.0

    VF_lo = 0.0
    VF_hi = 1.0
    for i in range(N):
        if Km1[i] < 0:
            bound = -1.0 / Km1[i]
            if bound < VF_hi:
                VF_hi = bound - 1e-15

    VF = (VF_lo + VF_hi) / 2.0

    for _ in range(300):
        f = 0.0
        df = 0.0
        for i in range(N):
            denom = 1.0 + VF * Km1[i]
            f += zs[i] * Km1[i] / denom
            df -= zs[i] * Km1[i] * Km1[i] / (denom * denom)

        if abs(f) < 1e-15:
            break

        if abs(df) < 1e-30:
            break

        VF_new = VF - f / df

        if VF_new <= VF_lo or VF_new >= VF_hi:
            if f > 0:
                VF_lo = VF
            else:
                VF_hi = VF
            VF_new = (VF_lo + VF_hi) / 2.0
        else:
            if f > 0:
                VF_lo = VF
            else:
                VF_hi = VF

        VF = VF_new

    return VF


def _wilson_k_values(T, P, Tcs, Pcs, omegas):
    """Wilson correlation K-value estimates."""
    N = len(Tcs)
    Ks = []
    for i in range(N):
        lnK = math.log(Pcs[i] / P) + 5.373 * (1.0 + omegas[i]) * (1.0 - Tcs[i] / T)
        Ks.append(math.exp(lnK))
    return Ks


def flash_pt(T, P, zs, Tcs, Pcs, omegas, kijs, maxiter=1000, tol=1e-12):
    """Two-phase isothermal-isobaric VLE flash via successive substitution."""
    N = len(zs)
    Ks = _wilson_k_values(T, P, Tcs, Pcs, omegas)

    for _ in range(maxiter):
        VF = rachford_rice(zs, Ks)

        xs = [zs[i] / (1.0 + VF * (Ks[i] - 1.0)) for i in range(N)]
        ys = [Ks[i] * xs[i] for i in range(N)]

        sx = sum(xs)
        sy = sum(ys)
        xs = [x / sx for x in xs]
        ys = [y / sy for y in ys]

        phis_l = mixture_fugacity_coefficients(T, P, xs, Tcs, Pcs, omegas, kijs, 'liquid')
        phis_g = mixture_fugacity_coefficients(T, P, ys, Tcs, Pcs, omegas, kijs, 'vapor')

        Ks_new = [phis_l[i] / phis_g[i] for i in range(N)]

        err = sum(
            (math.log(Ks_new[i]) - math.log(Ks[i])) ** 2
            for i in range(N)
        )
        Ks = Ks_new

        if err < tol:
            break

    VF = rachford_rice(zs, Ks)
    xs = [zs[i] / (1.0 + VF * (Ks[i] - 1.0)) for i in range(N)]
    ys = [Ks[i] * xs[i] for i in range(N)]
    sx = sum(xs)
    sy = sum(ys)
    xs = [x / sx for x in xs]
    ys = [y / sy for y in ys]

    return {'VF': VF, 'xs': xs, 'ys': ys}
