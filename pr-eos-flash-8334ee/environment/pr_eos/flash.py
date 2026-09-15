"""VLE flash calculation for PR EOS mixtures.

"""
import math
from .mixing import mix_params
from .cubic import solve_cubic_volumes
from .fugacity import fugacity_coefficients_from_V


def _get_fugacity_coefficients(T, P, zs, Tcs, Pcs, omegas, kijs, phase):
    """Internal helper to compute fugacity coefficients."""
    a_alpha_mix, b_mix, a_alpha_ijs, bs = mix_params(T, Tcs, Pcs, omegas, zs, kijs)
    volumes = solve_cubic_volumes(T, P, a_alpha_mix, b_mix)
    if not volumes:
        raise ValueError("No physical volume root found")
    V = volumes[0] if phase == 'liquid' else volumes[-1]
    return fugacity_coefficients_from_V(T, P, V, zs, a_alpha_mix, b_mix, a_alpha_ijs, bs)


def rachford_rice(zs, Ks):
    """Solve for equilibrium vapor fraction given feed compositions and K-values."""
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
    """Initial K-value estimates."""
    Ks = []
    for i in range(len(Tcs)):
        lnK = math.log(Pcs[i] / P) + 5.373 * (1.0 + omegas[i]) * (1.0 - Tcs[i] / T)
        Ks.append(math.exp(lnK))
    return Ks


def flash_pt(T, P, zs, Tcs, Pcs, omegas, kijs, maxiter=500, tol=1e-4):
    """Isothermal-isobaric two-phase flash.

    Returns dict with 'VF', 'xs', 'ys'.
    """
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

        phis_l = _get_fugacity_coefficients(T, P, xs, Tcs, Pcs, omegas, kijs, 'liquid')
        phis_g = _get_fugacity_coefficients(T, P, ys, Tcs, Pcs, omegas, kijs, 'vapor')

        Ks_new = [phis_l[i] / phis_g[i] for i in range(N)]

        # Convergence check on K-value changes
        err = sum(abs(Ks_new[i] - Ks[i]) for i in range(N))
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
