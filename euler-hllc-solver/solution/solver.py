#!/usr/bin/env python3
"""
First-order Godunov finite volume solver for 1D Euler equations
with HLLC flux, supporting multi-material (variable gamma) flows.
Includes a multi-gamma exact Riemann solver for error quantification.
"""

import json
import csv
import math
import os


def load_config():
    with open("/app/config/problems.json") as f:
        return json.load(f)


def get_gamma_lr(prob):
    gL = prob.get("gamma_left", prob.get("gamma", 1.4))
    gR = prob.get("gamma_right", prob.get("gamma", 1.4))
    return gL, gR


# =========================================================================
# HLLC flux (multi-gamma capable)
# =========================================================================

def hllc_flux(rhoL, uL, pL, gL, rhoR, uR, pR, gR):
    """Compute HLLC numerical flux. Returns (flux_vector, S_star)."""
    aL = math.sqrt(gL * pL / rhoL)
    aR = math.sqrt(gR * pR / rhoR)

    # Total energy per unit volume
    EL = pL / (gL - 1.0) + 0.5 * rhoL * uL * uL
    ER = pR / (gR - 1.0) + 0.5 * rhoR * uR * uR

    # PVRS pressure estimate
    rho_bar = 0.5 * (rhoL + rhoR)
    a_bar = 0.5 * (aL + aR)
    p_pvrs = 0.5 * (pL + pR) - 0.5 * (uR - uL) * rho_bar * a_bar
    p_est = max(p_pvrs, 0.0)

    # Wave speed estimates
    if p_est <= pL:
        qL = 1.0
    else:
        qL = math.sqrt(1.0 + (gL + 1.0) / (2.0 * gL) * (p_est / pL - 1.0))
    if p_est <= pR:
        qR = 1.0
    else:
        qR = math.sqrt(1.0 + (gR + 1.0) / (2.0 * gR) * (p_est / pR - 1.0))

    SL = uL - aL * qL
    SR = uR + aR * qR

    # Contact wave speed
    denom = rhoL * (SL - uL) - rhoR * (SR - uR)
    if abs(denom) < 1e-30:
        S_star = 0.5 * (uL + uR)
    else:
        S_star = (pR - pL + rhoL * uL * (SL - uL)
                  - rhoR * uR * (SR - uR)) / denom

    # Physical fluxes
    FL = [rhoL * uL, rhoL * uL * uL + pL, (EL + pL) * uL]
    FR = [rhoR * uR, rhoR * uR * uR + pR, (ER + pR) * uR]

    if SL >= 0.0:
        return FL, S_star
    elif SR <= 0.0:
        return FR, S_star
    elif S_star >= 0.0:
        UL = [rhoL, rhoL * uL, EL]
        coeff = rhoL * (SL - uL) / (SL - S_star)
        UL_s = [
            coeff,
            coeff * S_star,
            coeff * (EL / rhoL + (S_star - uL)
                     * (S_star + pL / (rhoL * (SL - uL)))),
        ]
        F = [FL[k] + SL * (UL_s[k] - UL[k]) for k in range(3)]
        return F, S_star
    else:
        UR = [rhoR, rhoR * uR, ER]
        coeff = rhoR * (SR - uR) / (SR - S_star)
        UR_s = [
            coeff,
            coeff * S_star,
            coeff * (ER / rhoR + (S_star - uR)
                     * (S_star + pR / (rhoR * (SR - uR)))),
        ]
        F = [FR[k] + SR * (UR_s[k] - UR[k]) for k in range(3)]
        return F, S_star


# =========================================================================
# Finite volume solver
# =========================================================================

def solve_problem(prob, n_cells=None):
    """Solve a 1D Riemann problem with Godunov + HLLC + gamma advection."""
    if n_cells is None:
        n_cells = prob["n_cells"]

    gamL, gamR = get_gamma_lr(prob)
    ls, rs = prob["left_state"], prob["right_state"]
    x0 = prob["diaphragm"]
    xmin, xmax = prob["domain"]
    t_final = prob["t_final"]
    cfl = prob.get("cfl", 0.8)

    dx = (xmax - xmin) / n_cells
    x = [xmin + (i + 0.5) * dx for i in range(n_cells)]

    # Initialise cell arrays
    rho = [0.0] * n_cells
    u = [0.0] * n_cells
    p = [0.0] * n_cells
    gam = [0.0] * n_cells

    for i in range(n_cells):
        if x[i] < x0:
            rho[i], u[i], p[i], gam[i] = (
                ls["density"], ls["velocity"], ls["pressure"], gamL)
        else:
            rho[i], u[i], p[i], gam[i] = (
                rs["density"], rs["velocity"], rs["pressure"], gamR)

    t = 0.0
    while t < t_final - 1e-14:
        # CFL time step
        max_speed = 0.0
        for i in range(n_cells):
            a = math.sqrt(gam[i] * p[i] / rho[i])
            max_speed = max(max_speed, abs(u[i]) + a)

        dt = cfl * dx / max_speed
        if t + dt > t_final:
            dt = t_final - t

        # Conservative variables [rho, rho*u, E]
        # E = total energy per unit volume = p/(gamma-1) + 0.5*rho*u^2
        U = [[0.0, 0.0, 0.0] for _ in range(n_cells)]
        for i in range(n_cells):
            E = p[i] / (gam[i] - 1.0) + 0.5 * rho[i] * u[i] * u[i]
            U[i] = [rho[i], rho[i] * u[i], E]

        rho_gam = [rho[i] * gam[i] for i in range(n_cells)]

        # Ghost cells (transmissive BC)
        rho_g = [rho[0]] + rho + [rho[-1]]
        u_g = [u[0]] + u + [u[-1]]
        p_g = [p[0]] + p + [p[-1]]
        gam_g = [gam[0]] + gam + [gam[-1]]

        # Compute HLLC fluxes at n_cells+1 interfaces
        fluxes = []
        s_stars = []
        for j in range(n_cells + 1):
            f, s_star = hllc_flux(
                rho_g[j], u_g[j], p_g[j], gam_g[j],
                rho_g[j + 1], u_g[j + 1], p_g[j + 1], gam_g[j + 1],
            )
            fluxes.append(f)
            s_stars.append(s_star)

        # Update conservative variables
        for i in range(n_cells):
            for k in range(3):
                U[i][k] -= dt / dx * (fluxes[i + 1][k] - fluxes[i][k])

        # Advect gamma using contact-wave upwinding
        for i in range(n_cells):
            # Upwind gamma at left interface (j=i) and right interface (j=i+1)
            gam_face_L = gam_g[i] if s_stars[i] >= 0 else gam_g[i + 1]
            gam_face_R = (gam_g[i + 1] if s_stars[i + 1] >= 0
                          else gam_g[i + 2])

            rho_gam[i] -= dt / dx * (
                fluxes[i + 1][0] * gam_face_R
                - fluxes[i][0] * gam_face_L
            )

        # Update primitive variables
        for i in range(n_cells):
            rho[i] = max(U[i][0], 1e-10)
            u[i] = U[i][1] / rho[i]
            gam[i] = rho_gam[i] / rho[i]
            gam[i] = max(1.01, min(3.0, gam[i]))  # clamp to physical range
            p[i] = (gam[i] - 1.0) * (U[i][2] - 0.5 * rho[i] * u[i] * u[i])
            p[i] = max(p[i], 1e-10)

        t += dt

    # Compute total specific energy for output
    energy = [p[i] / ((gam[i] - 1.0) * rho[i]) + 0.5 * u[i] * u[i]
              for i in range(n_cells)]

    return x, rho, u, p, energy, gam


# =========================================================================
# Multi-gamma exact Riemann solver
# =========================================================================

def exact_riemann(rhoL, uL, pL, gamL, rhoR, uR, pR, gamR, x0, t, x_arr):
    """Exact Riemann solver supporting different gamma on each side."""
    gm1L, gp1L = gamL - 1.0, gamL + 1.0
    g_ratL = gm1L / gp1L
    aL = math.sqrt(gamL * pL / rhoL)

    gm1R, gp1R = gamR - 1.0, gamR + 1.0
    g_ratR = gm1R / gp1R
    aR = math.sqrt(gamR * pR / rhoR)

    # Newton iteration for p*
    ppv = 0.5 * (pL + pR) - 0.125 * (uR - uL) * (rhoL + rhoR) * (aL + aR)
    p_star = max(ppv, 1e-10)

    for _ in range(300):
        if p_star <= pL:
            ratio = p_star / pL
            pwr = gm1L / (2.0 * gamL)
            fL = (2.0 * aL / gm1L) * (ratio ** pwr - 1.0)
            dfL = (1.0 / (rhoL * aL)) * ratio ** (-gp1L / (2.0 * gamL))
        else:
            A = 2.0 / (gp1L * rhoL)
            B = g_ratL * pL
            sq = math.sqrt(A / (p_star + B))
            fL = (p_star - pL) * sq
            dfL = sq * (1.0 - (p_star - pL) / (2.0 * (p_star + B)))

        if p_star <= pR:
            ratio = p_star / pR
            pwr = gm1R / (2.0 * gamR)
            fR = (2.0 * aR / gm1R) * (ratio ** pwr - 1.0)
            dfR = (1.0 / (rhoR * aR)) * ratio ** (-gp1R / (2.0 * gamR))
        else:
            A = 2.0 / (gp1R * rhoR)
            B = g_ratR * pR
            sq = math.sqrt(A / (p_star + B))
            fR = (p_star - pR) * sq
            dfR = sq * (1.0 - (p_star - pR) / (2.0 * (p_star + B)))

        f_val = fL + fR + (uR - uL)
        df_val = dfL + dfR
        if abs(df_val) < 1e-30:
            break
        p_new = max(p_star - f_val / df_val, 1e-10)
        if abs(p_new - p_star) / (0.5 * (p_new + p_star) + 1e-30) < 1e-12:
            p_star = p_new
            break
        p_star = p_new

    # Compute u*
    if p_star <= pL:
        fL_f = (2.0 * aL / gm1L) * (
            (p_star / pL) ** (gm1L / (2.0 * gamL)) - 1.0)
    else:
        A = 2.0 / (gp1L * rhoL)
        B = g_ratL * pL
        fL_f = (p_star - pL) * math.sqrt(A / (p_star + B))

    if p_star <= pR:
        fR_f = (2.0 * aR / gm1R) * (
            (p_star / pR) ** (gm1R / (2.0 * gamR)) - 1.0)
    else:
        A = 2.0 / (gp1R * rhoR)
        B = g_ratR * pR
        fR_f = (p_star - pR) * math.sqrt(A / (p_star + B))

    u_star = 0.5 * (uL + uR) + 0.5 * (fR_f - fL_f)

    results = []
    for x in x_arr:
        S = (x - x0) / t

        if S <= u_star:
            gm1 = gm1L
            gp1 = gp1L
            g_rat = g_ratL
            gam = gamL
            a0 = aL
            rho0, u0, p0 = rhoL, uL, pL

            if p_star <= p0:
                a_s = a0 * (p_star / p0) ** (gm1 / (2.0 * gam))
                S_H = u0 - a0
                S_T = u_star - a_s
                if S <= S_H:
                    rho_s, u_s, p_s = rho0, u0, p0
                elif S <= S_T:
                    base = 2.0 / gp1 + gm1 / (gp1 * a0) * (u0 - S)
                    rho_s = rho0 * base ** (2.0 / gm1)
                    u_s = 2.0 / gp1 * (a0 + gm1 / 2.0 * u0 + S)
                    p_s = p0 * base ** (2.0 * gam / gm1)
                else:
                    rho_s = rho0 * (p_star / p0) ** (1.0 / gam)
                    u_s, p_s = u_star, p_star
            else:
                S_sh = u0 - a0 * math.sqrt(
                    gp1 / (2.0 * gam) * (p_star / p0)
                    + gm1 / (2.0 * gam))
                if S <= S_sh:
                    rho_s, u_s, p_s = rho0, u0, p0
                else:
                    rho_s = rho0 * ((p_star / p0 + g_rat)
                                    / (g_rat * p_star / p0 + 1.0))
                    u_s, p_s = u_star, p_star
        else:
            gm1 = gm1R
            gp1 = gp1R
            g_rat = g_ratR
            gam = gamR
            a0 = aR
            rho0, u0, p0 = rhoR, uR, pR

            if p_star <= p0:
                a_s = a0 * (p_star / p0) ** (gm1 / (2.0 * gam))
                S_H = u0 + a0
                S_T = u_star + a_s
                if S >= S_H:
                    rho_s, u_s, p_s = rho0, u0, p0
                elif S >= S_T:
                    base = 2.0 / gp1 - gm1 / (gp1 * a0) * (u0 - S)
                    rho_s = rho0 * base ** (2.0 / gm1)
                    u_s = 2.0 / gp1 * (-a0 + gm1 / 2.0 * u0 + S)
                    p_s = p0 * base ** (2.0 * gam / gm1)
                else:
                    rho_s = rho0 * (p_star / p0) ** (1.0 / gam)
                    u_s, p_s = u_star, p_star
            else:
                S_sh = u0 + a0 * math.sqrt(
                    gp1 / (2.0 * gam) * (p_star / p0)
                    + gm1 / (2.0 * gam))
                if S >= S_sh:
                    rho_s, u_s, p_s = rho0, u0, p0
                else:
                    rho_s = rho0 * ((p_star / p0 + g_rat)
                                    / (g_rat * p_star / p0 + 1.0))
                    u_s, p_s = u_star, p_star

        E = p_s / ((gam - 1.0) * rho_s) + 0.5 * u_s ** 2
        results.append((rho_s, u_s, p_s, E, gam))

    return results


def compute_l1_error(numerical, exact_vals):
    n = len(numerical)
    return sum(abs(numerical[i] - exact_vals[i]) for i in range(n)) / n


# =========================================================================
# Main driver
# =========================================================================

def main():
    config = load_config()
    os.makedirs("/app/results", exist_ok=True)

    errors = {}

    for name in ["blast", "contact", "multigamma"]:
        print(f"Solving {name}...")
        prob = config["problems"][name]
        gamL, gamR = get_gamma_lr(prob)
        ls, rs = prob["left_state"], prob["right_state"]

        x, rho, u, p, energy, gam = solve_problem(prob)

        # Write CSV
        csv_path = f"/app/results/{name}.csv"
        is_multigamma = abs(gamL - gamR) > 0.001
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            if is_multigamma:
                writer.writerow(["x", "density", "velocity", "pressure",
                                 "energy", "gamma"])
                for i in range(len(x)):
                    writer.writerow([f"{x[i]:.12e}", f"{rho[i]:.12e}",
                                     f"{u[i]:.12e}", f"{p[i]:.12e}",
                                     f"{energy[i]:.12e}", f"{gam[i]:.12e}"])
            else:
                writer.writerow(["x", "density", "velocity", "pressure",
                                 "energy"])
                for i in range(len(x)):
                    writer.writerow([f"{x[i]:.12e}", f"{rho[i]:.12e}",
                                     f"{u[i]:.12e}", f"{p[i]:.12e}",
                                     f"{energy[i]:.12e}"])

        # Exact solution and error
        exact = exact_riemann(
            ls["density"], ls["velocity"], ls["pressure"], gamL,
            rs["density"], rs["velocity"], rs["pressure"], gamR,
            prob["diaphragm"], prob["t_final"], x,
        )
        exact_rho = [e[0] for e in exact]
        l1 = compute_l1_error(rho, exact_rho)
        errors[name] = l1
        print(f"  L1 density error: {l1:.6e}")

    with open("/app/results/errors.json", "w") as f:
        json.dump(errors, f, indent=2)

    # Convergence study
    print("Running convergence study...")
    conv_cfg = config["convergence"]
    prob_name = conv_cfg["problem"]
    prob = config["problems"][prob_name]
    gamL, gamR = get_gamma_lr(prob)
    ls, rs = prob["left_state"], prob["right_state"]
    xmin, xmax = prob["domain"]

    conv_errors = []
    for n in conv_cfg["resolutions"]:
        x, rho, u, p, energy, gam = solve_problem(prob, n_cells=n)
        exact = exact_riemann(
            ls["density"], ls["velocity"], ls["pressure"], gamL,
            rs["density"], rs["velocity"], rs["pressure"], gamR,
            prob["diaphragm"], prob["t_final"], x,
        )
        exact_rho = [e[0] for e in exact]
        l1 = compute_l1_error(rho, exact_rho)
        conv_errors.append(l1)
        print(f"  N={n}: L1 = {l1:.6e}")

    # Least-squares fit: log(error) = log(C) + rate * log(dx)
    log_dx = [math.log((xmax - xmin) / n) for n in conv_cfg["resolutions"]]
    log_err = [math.log(e) for e in conv_errors]

    n_pts = len(log_dx)
    sum_x = sum(log_dx)
    sum_y = sum(log_err)
    sum_xy = sum(log_dx[i] * log_err[i] for i in range(n_pts))
    sum_xx = sum(log_dx[i] ** 2 for i in range(n_pts))

    rate = (n_pts * sum_xy - sum_x * sum_y) / (n_pts * sum_xx - sum_x ** 2)

    conv_result = {
        "resolutions": conv_cfg["resolutions"],
        "errors": conv_errors,
        "rate": round(rate, 4),
    }

    with open("/app/results/convergence.json", "w") as f:
        json.dump(conv_result, f, indent=2)

    print(f"Convergence rate: {rate:.4f}")
    print("Done.")


if __name__ == "__main__":
    main()
