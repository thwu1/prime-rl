#!/usr/bin/env python3

"""
Structural mechanics verification engine.
Reads benchmark specifications from /app/benchmarks/*.json,
computes analytical/semi-analytical reference solutions,
and writes results to /app/results.json.
"""

import glob
import json
import math
import os
import sys

import numpy as np
from scipy.optimize import brentq


def solve_thick_cylinder(spec):
    """
    Plane-strain thermoelastic thick-walled hollow cylinder under
    internal pressure and logarithmic radial temperature gradient.

    Superposition of Lame mechanical solution and thermal stresses.
    Thermal stress formulas from Timoshenko & Goodier, Theory of Elasticity.
    """
    a = spec["geometry"]["inner_radius_m"]
    b = spec["geometry"]["outer_radius_m"]
    p_i = spec["loading"]["internal_pressure_MPa"]
    p_o = spec["loading"]["external_pressure_MPa"]
    E = spec["material"]["E_MPa"]
    nu = spec["material"]["nu"]
    alpha = spec["material"]["alpha_per_C"]
    T_inner = spec["loading"]["T_inner_C"]
    T_outer = spec["loading"]["T_outer_C"]

    eval_radii = spec["eval_radii_m"]

    a2 = a * a
    b2 = b * b
    ln_ba = math.log(b / a)
    dT = T_outer - T_inner

    def T(r):
        return T_inner + dT * math.log(r / a) / ln_ba

    # Integral I(x) = integral from a to x of T(r') * r' dr'
    C_coeff = dT / ln_ba

    def I_integral(x):
        x2 = x * x
        if abs(x - a) < 1e-15:
            return 0.0
        return (T_inner * (x2 - a2) / 2.0
                + C_coeff * (x2 / 2.0 * math.log(x / a) - (x2 - a2) / 4.0))

    I_b = I_integral(b)

    A_lame = (a2 * p_i - b2 * p_o) / (b2 - a2)
    B_lame = a2 * b2 * (p_i - p_o) / (b2 - a2)

    def sigma_r_mech(r):
        return A_lame - B_lame / (r * r)

    def sigma_theta_mech(r):
        return A_lame + B_lame / (r * r)

    aE_1mnu = alpha * E / (1.0 - nu)

    def sigma_r_th(r):
        r2 = r * r
        Ir = I_integral(r)
        return aE_1mnu * (-Ir / r2 + (r2 - a2) * I_b / (r2 * (b2 - a2)))

    def sigma_theta_th(r):
        r2 = r * r
        Ir = I_integral(r)
        return aE_1mnu * (Ir / r2 - T(r) + (r2 + a2) * I_b / (r2 * (b2 - a2)))

    def sigma_r_total(r):
        return sigma_r_mech(r) + sigma_r_th(r)

    def sigma_theta_total(r):
        return sigma_theta_mech(r) + sigma_theta_th(r)

    def u_r_total(r):
        sr = sigma_r_total(r)
        st = sigma_theta_total(r)
        eps_theta = ((1.0 + nu) / E * ((1.0 - nu) * st - nu * sr)
                     + (1.0 + nu) * alpha * T(r))
        return r * eps_theta

    results = {}
    for i, r in enumerate(eval_radii, 1):
        results[f"sigma_r_r{i}"] = sigma_r_total(r)
        results[f"sigma_theta_r{i}"] = sigma_theta_total(r)
        results[f"u_r_r{i}"] = u_r_total(r)

    return results


def solve_piston_fluid(spec):
    """
    First coupled eigenfrequency of a rigid piston closing one end
    of a fluid-filled tube with rigid far-end wall.
    """
    m = spec["piston"]["mass_kg"]
    S = spec["piston"]["area_m2"]
    rho = spec["fluid"]["density_kg_m3"]
    c = spec["fluid"]["speed_of_sound_m_s"]
    L = spec["fluid"]["column_length_m"]

    beta = rho * S * L / m

    def f(x):
        return x * math.tan(x) - beta

    x_root = brentq(f, 1e-6, math.pi / 2.0 - 1e-8, xtol=1e-14)

    omega = x_root * c / L
    freq = omega / (2.0 * math.pi)

    return {"freq_hz": freq}


def solve_foundation_buckling(spec):
    """
    Critical buckling load for simply-supported beam on elastic foundation.
    """
    EI = spec["beam"]["EI_Nm2"]
    L = spec["beam"]["length_m"]
    k = spec["foundation"]["k_N_per_m2"]
    pi2 = math.pi ** 2
    L2 = L * L

    def P_cr(n):
        return n * n * pi2 * EI / L2 + k * L2 / (n * n * pi2)

    n_opt_cont = (k * L ** 4 / (math.pi ** 4 * EI)) ** 0.25
    n_low = max(1, int(math.floor(n_opt_cont)))
    candidates = [(n, P_cr(n)) for n in range(max(1, n_low - 1), n_low + 3)]
    best_n, best_P = min(candidates, key=lambda x: x[1])

    return {"critical_load_N": best_P, "critical_mode": best_n}


def solve_plasticity_cycle(spec):
    """
    Uniaxial J2 elastoplastic response with linear isotropic hardening.
    Incremental stress integration through a multi-segment strain history.
    """
    E = spec["material"]["E_MPa"]
    sigma_y0 = spec["material"]["sigma_y_MPa"]
    H = spec["material"]["H_MPa"]
    segments = spec["strain_history"]["segment_endpoints"]
    n_inc = spec["strain_history"]["increments_per_segment"]

    sigma = 0.0
    eps_p = 0.0
    p_acc = 0.0

    strain_points = []
    for i in range(len(segments) - 1):
        e0 = segments[i]
        e1 = segments[i + 1]
        for j in range(n_inc):
            strain_points.append(e0 + (e1 - e0) * j / n_inc)
    strain_points.append(segments[-1])

    results_at_segments = {}

    for step in range(1, len(strain_points)):
        eps_new = strain_points[step]
        eps_old = strain_points[step - 1]
        d_eps = eps_new - eps_old

        sigma_trial = sigma + E * d_eps
        R = sigma_y0 + H * p_acc

        if abs(sigma_trial) <= R * (1.0 + 1e-12):
            sigma = sigma_trial
        else:
            dp = (abs(sigma_trial) - R) / (E + H)
            p_acc += dp
            R_new = sigma_y0 + H * p_acc
            sign_s = 1.0 if sigma_trial >= 0 else -1.0
            sigma = sign_s * R_new
            eps_p += sign_s * dp

        if step == n_inc:
            results_at_segments["peak"] = {"sigma": sigma, "p_acc": p_acc}
        elif step == 2 * n_inc:
            results_at_segments["final"] = {"sigma": sigma, "p_acc": p_acc}

    if "final" not in results_at_segments:
        results_at_segments["final"] = {"sigma": sigma, "p_acc": p_acc}

    return {
        "sigma_at_peak_MPa": results_at_segments["peak"]["sigma"],
        "eps_p_acc_at_peak": results_at_segments["peak"]["p_acc"],
        "sigma_at_final_MPa": results_at_segments["final"]["sigma"],
        "eps_p_acc_at_final": results_at_segments["final"]["p_acc"],
    }


def solve_composite_laminate(spec):
    """
    Classical Lamination Theory: effective properties and ply stresses
    of a symmetric laminate under in-plane loading.
    """
    E1 = spec["ply_material"]["E1_MPa"]
    E2 = spec["ply_material"]["E2_MPa"]
    G12 = spec["ply_material"]["G12_MPa"]
    nu12 = spec["ply_material"]["nu12"]
    nu21 = nu12 * E2 / E1

    denom = 1.0 - nu12 * nu21
    Q = np.array([
        [E1 / denom,       nu12 * E2 / denom, 0.0],
        [nu12 * E2 / denom, E2 / denom,        0.0],
        [0.0,               0.0,               G12],
    ])

    angles = spec["layup"]["angles_deg"]
    t_ply = spec["layup"]["ply_thickness_mm"]
    n_plies = len(angles)
    h_total = n_plies * t_ply

    def Qbar(theta_deg):
        th = math.radians(theta_deg)
        c = math.cos(th)
        s = math.sin(th)
        c2, s2, cs = c * c, s * s, c * s
        c4, s4, c2s2 = c2 * c2, s2 * s2, c2 * s2
        Q11, Q12_, Q22, Q66 = Q[0, 0], Q[0, 1], Q[1, 1], Q[2, 2]

        Qb = np.zeros((3, 3))
        Qb[0, 0] = Q11 * c4 + 2.0 * (Q12_ + 2.0 * Q66) * c2s2 + Q22 * s4
        Qb[1, 1] = Q11 * s4 + 2.0 * (Q12_ + 2.0 * Q66) * c2s2 + Q22 * c4
        Qb[0, 1] = (Q11 + Q22 - 4.0 * Q66) * c2s2 + Q12_ * (c4 + s4)
        Qb[1, 0] = Qb[0, 1]
        Qb[2, 2] = (Q11 + Q22 - 2.0 * Q12_ - 2.0 * Q66) * c2s2 + Q66 * (c4 + s4)
        Qb[0, 2] = (Q11 - Q12_ - 2.0 * Q66) * c2 * cs - (Q22 - Q12_ - 2.0 * Q66) * s2 * cs
        Qb[2, 0] = Qb[0, 2]
        Qb[1, 2] = (Q11 - Q12_ - 2.0 * Q66) * s2 * cs - (Q22 - Q12_ - 2.0 * Q66) * c2 * cs
        Qb[2, 1] = Qb[1, 2]
        return Qb

    # Assemble extensional stiffness matrix A
    A_mat = np.zeros((3, 3))
    for angle in angles:
        A_mat += Qbar(angle) * t_ply

    # Compliance
    a_mat = np.linalg.inv(A_mat)

    # Effective engineering constants
    Ex = 1.0 / (h_total * a_mat[0, 0])
    Ey = 1.0 / (h_total * a_mat[1, 1])
    Gxy = 1.0 / (h_total * a_mat[2, 2])
    nuxy = -a_mat[0, 1] / a_mat[0, 0]

    # Mid-plane strains
    Nx = spec["loading_N_per_mm"]["Nx"]
    Ny = spec["loading_N_per_mm"]["Ny"]
    Nxy = spec["loading_N_per_mm"]["Nxy"]
    N_vec = np.array([Nx, Ny, Nxy])
    eps_0 = a_mat @ N_vec

    # Ply stresses in material coordinates
    def ply_stress(eps_global, theta_deg):
        th = math.radians(theta_deg)
        c = math.cos(th)
        s = math.sin(th)
        c2, s2, cs = c * c, s * s, c * s

        T_eps = np.array([
            [c2,     s2,      cs],
            [s2,     c2,     -cs],
            [-2*cs,  2*cs,  c2 - s2],
        ])
        eps_mat = T_eps @ eps_global
        return Q @ eps_mat

    sig_0 = ply_stress(eps_0, 0)
    sig_90 = ply_stress(eps_0, 90)

    return {
        "Ex_eff_MPa": float(Ex),
        "Ey_eff_MPa": float(Ey),
        "Gxy_eff_MPa": float(Gxy),
        "nuxy_eff": float(nuxy),
        "eps_x_0": float(eps_0[0]),
        "eps_y_0": float(eps_0[1]),
        "gamma_xy_0": float(eps_0[2]),
        "sigma_1_ply0_MPa": float(sig_0[0]),
        "sigma_2_ply0_MPa": float(sig_0[1]),
        "tau_12_ply0_MPa": float(sig_0[2]),
        "sigma_1_ply90_MPa": float(sig_90[0]),
        "sigma_2_ply90_MPa": float(sig_90[1]),
        "tau_12_ply90_MPa": float(sig_90[2]),
    }


SOLVERS = {
    "thermoelastic_cylinder": solve_thick_cylinder,
    "coupled_piston_fluid": solve_piston_fluid,
    "beam_foundation_buckling": solve_foundation_buckling,
    "j2_plasticity_uniaxial": solve_plasticity_cycle,
    "classical_lamination": solve_composite_laminate,
}


def main():
    benchmarks_dir = "/app/benchmarks"
    results = {"benchmarks": {}}

    json_files = sorted(glob.glob(os.path.join(benchmarks_dir, "*.json")))
    if not json_files:
        print(f"ERROR: No benchmark files found in {benchmarks_dir}", file=sys.stderr)
        sys.exit(1)

    for fpath in json_files:
        with open(fpath) as f:
            spec = json.load(f)

        name = spec["name"]
        btype = spec["type"]

        solver = SOLVERS.get(btype)
        if solver is None:
            print(f"WARNING: Unknown benchmark type '{btype}' in {fpath}", file=sys.stderr)
            continue

        print(f"Solving benchmark: {name} (type: {btype})")
        result = solver(spec)
        results["benchmarks"][name] = result
        print(f"  -> {len(result)} outputs computed")

    output_path = "/app/results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
