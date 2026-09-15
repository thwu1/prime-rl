#!/usr/bin/env python3
"""
Peng-Robinson EOS isothermal (PT) flash calculator for multicomponent mixtures.
Implements: cubic solver, mixing rules, fugacity coefficients,
Rachford-Rice, successive substitution, departure properties.

Known issues: results do not match reference implementations for some systems.
"""

import json
import math
import sys

R = 8.314462618  # J/(mol*K)

C1 = 0.4572355289213821893834601962251837888504
C2 = 0.0777960739038884559718447100373331839711
SQRT2 = math.sqrt(2.0)
ONE_PLUS_SQRT2 = 1.0 + SQRT2
SQRT2_MINUS_ONE = SQRT2 - 1.0
TWO_SQRT2 = 2.0 * SQRT2


def pr_pure_params(Tc, Pc, omega):
    """Compute pure-component PR EOS parameters."""
    a = C1 * R * R * Tc * Tc / Pc
    b = C2 * R * Tc / Pc
    kappa = 0.37464 + 1.54226 * omega - 0.26992 * omega * omega * omega
    return a, b, kappa


def a_alpha_and_deriv(a, kappa, T, Tc):
    """Compute a*alpha(T) and its temperature derivative."""
    sqrt_Tr = math.sqrt(T / Tc)
    x = 1.0 + kappa * (1.0 - sqrt_Tr)
    a_alpha = a * x * x
    da_alpha_dT = -a * kappa * x / math.sqrt(T * Tc)
    return a_alpha, da_alpha_dT


def mix_params(zs, a_alphas, da_alpha_dTs, bs, kijs, N):
    """
    Van der Waals one-fluid mixing rules.
    Returns (a_alpha_mix, b_mix, a_alpha_ij matrix, da_alpha_dT_mix).
    """
    a_alpha_ij = [[0.0] * N for _ in range(N)]
    a_alpha_mix = 0.0
    da_alpha_dT_mix = 0.0
    b_mix = 0.0

    for i in range(N):
        b_mix += zs[i] * bs[i]

    for i in range(N):
        for j in range(N):
            omk = 1.0 - kijs[i][j]
            aij = omk * 0.5 * (a_alphas[i] + a_alphas[j])
            a_alpha_ij[i][j] = aij
            a_alpha_mix += zs[i] * zs[j] * aij

    for i in range(N):
        for j in range(N):
            omk = 1.0 - kijs[i][j]
            prod = a_alphas[i] * a_alphas[j]
            if prod > 0.0:
                sqrt_prod = math.sqrt(prod)
                cross = (da_alpha_dTs[i] * a_alphas[j] +
                         a_alphas[i] * da_alpha_dTs[j]) / (2.0 * sqrt_prod)
                da_alpha_dT_mix += zs[i] * zs[j] * omk * cross

    return a_alpha_mix, b_mix, a_alpha_ij, da_alpha_dT_mix


def solve_cubic_pr(A, B):
    """
    Solve the PR cubic:
      Z^3 - (1-B)*Z^2 + (A - 3B^2 - 2B)*Z - (AB - B^2 - B^3) = 0

    Returns sorted list of real roots.
    """
    c2 = -(1.0 - B)
    c1 = A - 3.0 * B * B - 2.0 * B
    c0 = -(A * B - B * B - B * B * B)

    c2_3 = c2 / 3.0
    p = c1 - c2 * c2_3
    q = c0 - c1 * c2_3 + 2.0 * c2_3 * c2_3 * c2_3

    disc = (q / 2.0) ** 2 + (p / 3.0) ** 3

    roots = []
    if disc < -1e-30:
        m = math.sqrt(-p / 3.0)
        cos_arg = -q / (2.0 * m * m * m)
        cos_arg = max(-1.0, min(1.0, cos_arg))
        theta = math.acos(cos_arg) / 3.0
        for k in range(3):
            t = 2.0 * m * math.cos(theta - 2.0 * math.pi * k / 3.0)
            roots.append(t - c2_3)
    elif disc > 1e-30:
        sqrt_disc = math.sqrt(disc)
        u_arg = -q / 2.0 + sqrt_disc
        v_arg = -q / 2.0 - sqrt_disc
        u = math.copysign(abs(u_arg) ** (1.0 / 3.0), u_arg)
        v = math.copysign(abs(v_arg) ** (1.0 / 3.0), v_arg)
        roots.append(u + v - c2_3)
    else:
        if abs(q) < 1e-30:
            roots.append(-c2_3)
        else:
            u = math.copysign(abs(q / 2.0) ** (1.0 / 3.0), -q)
            roots.append(2.0 * u - c2_3)
            roots.append(-u - c2_3)

    roots.sort()
    return roots


def pr_lnphi(Z, A, B, N, zs, bs, b_mix, a_alpha_mix, a_alpha_ij):
    """
    Fugacity coefficients for each component in a PR mixture.
    """
    lnphis = [0.0] * N
    if a_alpha_mix == 0.0 or b_mix == 0.0 or B == 0.0:
        return lnphis

    zmb = Z - B
    if zmb <= 0.0:
        zmb = 1e-30

    log_zmb = math.log(zmb)

    numer = Z + ONE_PLUS_SQRT2 * B
    denom = Z - SQRT2_MINUS_ONE * B
    if denom <= 0.0:
        denom = 1e-30
    log_ratio = math.log(numer / denom)

    A_over_2s2B = A / (TWO_SQRT2 * B)

    for i in range(N):
        bi_over_b = bs[i] / b_mix
        sum_j = 0.0
        for j in range(N):
            sum_j += zs[j] * a_alpha_ij[i][j]

        bracket = bi_over_b - 2.0 * sum_j / a_alpha_mix
        lnphis[i] = bi_over_b * (Z - 1.0) - log_zmb + A_over_2s2B * bracket * log_ratio

    return lnphis


def departure_props(T, P, Z, b_mix, a_alpha_mix, da_alpha_dT_mix):
    """Compute departure enthalpy [J/mol] and entropy [J/(mol*K)]."""
    B = b_mix * P / (R * T)
    zmb = Z - B
    if zmb <= 0.0:
        zmb = 1e-30

    numer = Z + ONE_PLUS_SQRT2 * B
    denom = Z - SQRT2_MINUS_ONE * B
    if denom <= 0.0:
        denom = 1e-30
    log_ratio = math.log(numer / denom)

    coeff = 1.0 / (TWO_SQRT2 * b_mix)

    H_dep = R * T * (Z - 1.0) + (T * da_alpha_dT_mix + a_alpha_mix) * coeff * log_ratio
    S_dep = R * math.log(zmb) + da_alpha_dT_mix * coeff * log_ratio

    return H_dep, S_dep


def wilson_k_values(T, P, Tcs, Pcs, omegas, N):
    """Wilson's correlation for initial K-value estimates."""
    Ks = [0.0] * N
    T_inv = 1.0 / T
    P_inv = 1.0 / P
    for i in range(N):
        Ks[i] = Pcs[i] * P_inv * math.exp(5.37 * (1.0 + omegas[i]) * (1.0 - Tcs[i] * T_inv))
    return Ks


def rachford_rice(zs, Ks, N):
    """
    Solve the Rachford-Rice equation for V/F.
    Returns (V_over_F, xs, ys) or None if no two-phase solution.
    """
    Kmin, Kmax = 1e300, -1e300
    z_of_Kmax = 0.0
    for i in range(N):
        if zs[i] > 0.0:
            if Ks[i] > Kmax:
                Kmax = Ks[i]
                z_of_Kmax = zs[i]
            if Ks[i] < Kmin:
                Kmin = Ks[i]

    if Kmin >= 1.0 - 1e-15 or Kmax <= 1.0 + 1e-15:
        return None

    VF_min = ((Kmax - Kmin) * z_of_Kmax - (1.0 - Kmin)) / ((1.0 - Kmin) * (Kmax - 1.0))
    VF_max = 1.0 / (1.0 - Kmin)

    VF_min = max(0.0, VF_min)
    VF_max = min(1.0, VF_max)
    if VF_min >= VF_max:
        return None

    K_minus_1 = [Ks[i] - 1.0 for i in range(N)]
    zK = [zs[i] * K_minus_1[i] for i in range(N)]

    def obj(VF):
        s = 0.0
        for i in range(N):
            s += zK[i] / (1.0 + VF * K_minus_1[i])
        return s

    def obj_deriv(VF):
        s = 0.0
        for i in range(N):
            denom = 1.0 + VF * K_minus_1[i]
            s -= zK[i] * K_minus_1[i] / (denom * denom)
        return s

    lo = VF_min + 1e-14
    hi = VF_max - 1e-14
    VF = 0.5 * (lo + hi)

    for _ in range(100):
        f = obj(VF)
        fp = obj_deriv(VF)
        if abs(fp) > 1e-30:
            step = -f / fp
            VF_new = VF + step
            if VF_new <= lo or VF_new >= hi:
                VF_new = 0.5 * (lo + hi)
        else:
            VF_new = 0.5 * (lo + hi)

        f_new = obj(VF_new)
        if f_new > 0:
            lo = VF_new
        else:
            hi = VF_new
        VF = VF_new
        if abs(f_new) < 1e-15:
            break

    xs = [0.0] * N
    ys = [0.0] * N
    for i in range(N):
        xs[i] = zs[i] / (1.0 + VF * K_minus_1[i])
        ys[i] = Ks[i] * xs[i]

    sx = sum(xs)
    sy = sum(ys)
    for i in range(N):
        xs[i] /= sx
        ys[i] /= sy

    return VF, xs, ys


def select_liquid_root(roots, B):
    """Select the liquid Z root: smallest positive root."""
    candidates = [z for z in roots if z > 1e-15]
    return min(candidates) if candidates else roots[-1]


def select_vapor_root(roots, B):
    """Select the vapor Z root: largest positive root."""
    candidates = [z for z in roots if z > 1e-15]
    return max(candidates) if candidates else roots[-1]


def evaluate_phase(zs, T, P, a_alphas, da_alpha_dTs, bs, kijs, N, phase):
    """
    Compute EOS properties for a single phase.
    Returns (phis, lnphis, Z, H_dep, S_dep).
    """
    a_alpha_mix, b_mix, a_alpha_ij, da_dT_mix = mix_params(
        zs, a_alphas, da_alpha_dTs, bs, kijs, N
    )
    A = a_alpha_mix * P / (R * R * T * T)
    B = b_mix * P / (R * T)

    roots = solve_cubic_pr(A, B)
    if phase == "liquid":
        Z = select_liquid_root(roots, B)
    else:
        Z = select_vapor_root(roots, B)

    lnphis = pr_lnphi(Z, A, B, N, zs, bs, b_mix, a_alpha_mix, a_alpha_ij)
    phis = [math.exp(lp) for lp in lnphis]

    H_dep, S_dep = departure_props(T, P, Z, b_mix, a_alpha_mix, da_dT_mix)

    return phis, lnphis, Z, H_dep, S_dep


def pt_flash(Tcs, Pcs, omegas, zs, T, P, kijs=None):
    """
    Perform an isothermal PT flash using the Peng-Robinson EOS.
    """
    N = len(Tcs)
    if kijs is None:
        kijs = [[0.0] * N for _ in range(N)]

    params = [pr_pure_params(Tcs[i], Pcs[i], omegas[i]) for i in range(N)]
    ais = [p[0] for p in params]
    bis = [p[1] for p in params]
    kappas = [p[2] for p in params]

    aa_da = [a_alpha_and_deriv(ais[i], kappas[i], T, Tcs[i]) for i in range(N)]
    a_alphas = [x[0] for x in aa_da]
    da_alpha_dTs = [x[1] for x in aa_da]

    Ks = wilson_k_values(T, P, Tcs, Pcs, omegas, N)

    all_gt1 = all(K > 1.0 for K in Ks)
    all_lt1 = all(K < 1.0 for K in Ks)

    if all_gt1:
        phis_g, _, Z_g, H_dep_g, S_dep_g = evaluate_phase(
            zs, T, P, a_alphas, da_alpha_dTs, bis, kijs, N, "vapor"
        )
        return {
            "V_over_F": 2.0,
            "xs": None, "ys": list(zs),
            "phis_l": None, "phis_g": phis_g,
            "K_values": None,
            "H_dep_l": None, "H_dep_g": H_dep_g,
            "S_dep_l": None, "S_dep_g": S_dep_g,
        }
    if all_lt1:
        phis_l, _, Z_l, H_dep_l, S_dep_l = evaluate_phase(
            zs, T, P, a_alphas, da_alpha_dTs, bis, kijs, N, "liquid"
        )
        return {
            "V_over_F": -1.0,
            "xs": list(zs), "ys": None,
            "phis_l": phis_l, "phis_g": None,
            "K_values": None,
            "H_dep_l": H_dep_l, "H_dep_g": None,
            "S_dep_l": S_dep_l, "S_dep_g": None,
        }

    VF = 0.5
    xs = list(zs)
    ys = list(zs)
    converged = False

    for iteration in range(500):
        rr_result = rachford_rice(zs, Ks, N)
        if rr_result is None:
            if sum(Ks[i] * zs[i] for i in range(N)) < 1.0:
                phis_l, _, _, H_dep_l, S_dep_l = evaluate_phase(
                    zs, T, P, a_alphas, da_alpha_dTs, bis, kijs, N, "liquid"
                )
                return {
                    "V_over_F": -1.0,
                    "xs": list(zs), "ys": None,
                    "phis_l": phis_l, "phis_g": None,
                    "K_values": None,
                    "H_dep_l": H_dep_l, "H_dep_g": None,
                    "S_dep_l": S_dep_l, "S_dep_g": None,
                }
            else:
                phis_g, _, _, H_dep_g, S_dep_g = evaluate_phase(
                    zs, T, P, a_alphas, da_alpha_dTs, bis, kijs, N, "vapor"
                )
                return {
                    "V_over_F": 2.0,
                    "xs": None, "ys": list(zs),
                    "phis_l": None, "phis_g": phis_g,
                    "K_values": None,
                    "H_dep_l": None, "H_dep_g": H_dep_g,
                    "S_dep_l": None, "S_dep_g": S_dep_g,
                }

        VF, xs, ys = rr_result

        phis_l, lnphis_l, Z_l, H_dep_l, S_dep_l = evaluate_phase(
            xs, T, P, a_alphas, da_alpha_dTs, bis, kijs, N, "liquid"
        )
        phis_g, lnphis_g, Z_g, H_dep_g, S_dep_g = evaluate_phase(
            ys, T, P, a_alphas, da_alpha_dTs, bis, kijs, N, "vapor"
        )

        Ks_new = [0.0] * N
        max_dlnK = 0.0
        for i in range(N):
            Ks_new[i] = phis_l[i] / phis_g[i]
            if Ks[i] > 0.0 and Ks_new[i] > 0.0:
                dlnK = abs(math.log(Ks_new[i]) - math.log(Ks[i]))
                if dlnK > max_dlnK:
                    max_dlnK = dlnK

        Ks = Ks_new

        if max_dlnK < 1e-10:
            converged = True
            break

    if VF < -1e-6:
        phis_l, _, _, H_dep_l, S_dep_l = evaluate_phase(
            zs, T, P, a_alphas, da_alpha_dTs, bis, kijs, N, "liquid"
        )
        return {
            "V_over_F": -1.0,
            "xs": list(zs), "ys": None,
            "phis_l": phis_l, "phis_g": None,
            "K_values": None,
            "H_dep_l": H_dep_l, "H_dep_g": None,
            "S_dep_l": S_dep_l, "S_dep_g": None,
        }
    elif VF > 1.0 + 1e-6:
        phis_g, _, _, H_dep_g, S_dep_g = evaluate_phase(
            zs, T, P, a_alphas, da_alpha_dTs, bis, kijs, N, "vapor"
        )
        return {
            "V_over_F": 2.0,
            "xs": None, "ys": list(zs),
            "phis_l": None, "phis_g": phis_g,
            "K_values": None,
            "H_dep_l": None, "H_dep_g": H_dep_g,
            "S_dep_l": None, "S_dep_g": S_dep_g,
        }

    return {
        "V_over_F": VF,
        "xs": xs,
        "ys": ys,
        "phis_l": phis_l,
        "phis_g": phis_g,
        "K_values": Ks,
        "H_dep_l": H_dep_l,
        "H_dep_g": H_dep_g,
        "S_dep_l": S_dep_l,
        "S_dep_g": S_dep_g,
    }


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.json output.json", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        spec = json.load(f)

    result = pt_flash(
        Tcs=spec["Tcs"],
        Pcs=spec["Pcs"],
        omegas=spec["omegas"],
        zs=spec["zs"],
        T=spec["T"],
        P=spec["P"],
        kijs=spec.get("kijs"),
    )

    with open(sys.argv[2], "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
