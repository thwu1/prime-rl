#!/usr/bin/env python3
"""Parse OpenFOAM case files and run Riemann + KT analysis.

"""
import os
import re
import json
import csv
import numpy as np

import riemann
import kt_solver


# ---------------------------------------------------------------------------
# OpenFOAM file parsers
# ---------------------------------------------------------------------------

def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    return text


def parse_zonal_scalar(path):
    raw = _strip_comments(open(path).read())
    default = float(re.search(r"defaultValue\s+([\d.eE+-]+)", raw).group(1))
    zone_val = float(re.search(r"zones\s*\{.*?value\s+([\d.eE+-]+)", raw, re.DOTALL).group(1))
    box_m = re.search(r"box\s*\(([\d.eE+\-\s]+)\)\s*\(([\d.eE+\-\s]+)\)", raw)
    box_min = [float(v) for v in box_m.group(1).split()]
    return default, zone_val, box_min[0]


def parse_zonal_vector(path):
    raw = _strip_comments(open(path).read())
    default = [float(v) for v in re.search(
        r"defaultValue\s*\(([\d.eE+\-\s]+)\)", raw).group(1).split()]
    zone_val = [float(v) for v in re.search(
        r"zones\s*\{.*?value\s*\(([\d.eE+\-\s]+)\)", raw, re.DOTALL).group(1).split()]
    return default, zone_val


def parse_gas(path):
    raw = _strip_comments(open(path).read())
    Cp = float(re.search(r"Cp\s+([\d.eE+-]+)", raw).group(1))
    Cv = float(re.search(r"Cv\s+([\d.eE+-]+)", raw).group(1))
    gamma = Cp / Cv
    R = Cp - Cv
    return gamma, R


def parse_block_mesh(path):
    raw = _strip_comments(open(path).read())
    vert_block = re.search(r"vertices\s*\((.*?)\)\s*;", raw, re.DOTALL).group(1)
    xs = [float(m.group(1)) for m in re.finditer(r"\(\s*([\d.eE+-]+)", vert_block)]
    blk = re.search(r"hex\s*\([\d\s]+\)\s*\((\d+)", raw)
    return min(xs), max(xs), int(blk.group(1))


def parse_end_time(path):
    raw = _strip_comments(open(path).read())
    return float(re.search(r"endTime\s+([\d.eE+-]+)", raw).group(1))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    case = "/app/case"

    pL, pR, x0 = parse_zonal_scalar(f"{case}/0/p")
    uL_vec, uR_vec = parse_zonal_vector(f"{case}/0/U")
    TL, TR, _ = parse_zonal_scalar(f"{case}/0/T")
    gamma, R = parse_gas(f"{case}/constant/thermophysicalProperties")
    x_left, x_right, _ = parse_block_mesh(f"{case}/system/blockMeshDict")
    t_end = parse_end_time(f"{case}/system/controlDict")

    rhoL = pL / (R * TL)
    rhoR = pR / (R * TR)
    uL = uL_vec[0]
    uR = uR_vec[0]

    print(f"Left:  rho={rhoL:.6f}  u={uL:.6f}  p={pL:.6f}")
    print(f"Right: rho={rhoR:.6f}  u={uR:.6f}  p={pR:.6f}")
    print(f"gamma={gamma:.4f}  domain=[{x_left},{x_right}]  x0={x0}  t_end={t_end}")

    os.makedirs("/app/results", exist_ok=True)

    # 1. Exact solution
    sol = riemann.solve(rhoL, uL, pL, rhoR, uR, pR, gamma)
    gm1 = gamma - 1.0

    x_pts = np.linspace(x_left, x_right, 1000)
    with open("/app/results/exact_solution.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["x", "rho", "u", "p", "e"])
        for xv in x_pts:
            rho, u, p = riemann.sample(xv, t_end, x0, rhoL, uL, pL, rhoR, uR, pR, gamma)
            e = p / (rho * gm1)
            w.writerow([f"{xv:.6f}", f"{rho:.6f}", f"{u:.6f}", f"{p:.6f}", f"{e:.6f}"])

    # 2. Numerical solutions & convergence
    Ns = [100, 200, 400]
    L1 = {"rho": [], "u": [], "p": []}

    for N in Ns:
        xc, rho_n, u_n, p_n = kt_solver.solve(
            rhoL, uL, pL, rhoR, uR, pR, gamma,
            x_left, x_right, x0, t_end, N, cfl=0.5,
        )
        # Write CSV
        with open(f"/app/results/numerical_{N}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["x", "rho", "u", "p"])
            for i in range(N):
                w.writerow([f"{xc[i]:.6f}", f"{rho_n[i]:.6f}",
                            f"{u_n[i]:.6f}", f"{p_n[i]:.6f}"])

        # Exact at cell centres
        dx = (x_right - x_left) / N
        rho_e = np.array([riemann.sample(xv, t_end, x0, rhoL, uL, pL,
                                          rhoR, uR, pR, gamma)[0] for xv in xc])
        u_e = np.array([riemann.sample(xv, t_end, x0, rhoL, uL, pL,
                                        rhoR, uR, pR, gamma)[1] for xv in xc])
        p_e = np.array([riemann.sample(xv, t_end, x0, rhoL, uL, pL,
                                        rhoR, uR, pR, gamma)[2] for xv in xc])
        L1["rho"].append(float(np.sum(np.abs(rho_n - rho_e)) * dx))
        L1["u"].append(float(np.sum(np.abs(u_n - u_e)) * dx))
        L1["p"].append(float(np.sum(np.abs(p_n - p_e)) * dx))

    rates = {}
    for var in ["rho", "u", "p"]:
        e = L1[var]
        rates[var] = float(np.log(e[0] / e[2]) / np.log(4))

    with open("/app/results/convergence.json", "w") as f:
        json.dump({"L1_errors": L1, "convergence_rates": rates}, f, indent=2)

    # 3. Wave structure
    aL_val = np.sqrt(gamma * pL / rhoL)
    aR_val = np.sqrt(gamma * pR / rhoR)
    ps = sol["p_star"]
    us = sol["u_star"]

    wave = {"star_region": {
        "pressure": ps, "velocity": us,
        "density_left": sol["rho_star_L"], "density_right": sol["rho_star_R"],
    }, "contact": {"speed": us}}

    if ps <= pL:
        asL = aL_val * (ps / pL) ** ((gamma - 1) / (2 * gamma))
        wave["left_wave"] = {"type": "rarefaction",
                             "head_speed": float(uL - aL_val),
                             "tail_speed": float(us - asL)}
    else:
        SL = uL - aL_val * np.sqrt((gamma + 1) / (2 * gamma) * ps / pL +
                                    (gamma - 1) / (2 * gamma))
        wave["left_wave"] = {"type": "shock", "speed": float(SL)}

    if ps <= pR:
        asR = aR_val * (ps / pR) ** ((gamma - 1) / (2 * gamma))
        wave["right_wave"] = {"type": "rarefaction",
                              "head_speed": float(uR + aR_val),
                              "tail_speed": float(us + asR)}
    else:
        SR = uR + aR_val * np.sqrt((gamma + 1) / (2 * gamma) * ps / pR +
                                    (gamma - 1) / (2 * gamma))
        wave["right_wave"] = {"type": "shock", "speed": float(SR)}

    with open("/app/results/wave_structure.json", "w") as f:
        json.dump(wave, f, indent=2)

    print("Done. Results written to /app/results/")


if __name__ == "__main__":
    main()
