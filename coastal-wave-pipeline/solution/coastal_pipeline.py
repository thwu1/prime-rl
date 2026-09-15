#!/usr/bin/env python3
"""
Coastal wave transformation pipeline per USACE CEM (EM 1110-2-1100).
Uses C shared library for dispersion relation solver via ctypes.
Stores results in SQLite database.
"""

import sys
import json
import math
import csv
import os
import ctypes
import sqlite3

G = 9.81  # gravitational acceleration (m/s^2)

# ---------------------------------------------------------------------------
# Load C dispersion library
# ---------------------------------------------------------------------------
_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "libdispersion.so")
_lib = ctypes.CDLL(_lib_path)
_lib.solve_dispersion.argtypes = [
    ctypes.c_double, ctypes.c_double, ctypes.POINTER(ctypes.c_double)
]
_lib.solve_dispersion.restype = ctypes.c_int


def solve_dispersion(T, d):
    """Call C library to solve the dispersion relation."""
    out = (ctypes.c_double * 5)()
    ret = _lib.solve_dispersion(T, d, out)
    if ret != 0:
        raise RuntimeError(f"C dispersion solver failed for T={T}, d={d}")
    return {"d": d, "L": out[0], "C": out[1], "Cg": out[2], "k": out[3], "n": out[4]}


# ---------------------------------------------------------------------------
# SQLite result storage
# ---------------------------------------------------------------------------
def init_db(db_path="/app/results.db"):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scenario_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_name TEXT UNIQUE,
            mode TEXT,
            input_json TEXT,
            output_json TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def save_result(conn, name, mode, input_json, output_json):
    conn.execute(
        "INSERT OR REPLACE INTO scenario_results "
        "(scenario_name, mode, input_json, output_json) VALUES (?, ?, ?, ?)",
        (name, mode, input_json, output_json)
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Shoaling and refraction along a transect
# ---------------------------------------------------------------------------
def compute_transect(H0, T, theta0_deg, depths):
    Lo = G * T ** 2 / (2.0 * math.pi)
    Co = Lo / T
    Cgo = Co / 2.0
    theta0 = math.radians(theta0_deg)

    results = []
    for d in depths:
        disp = solve_dispersion(T, d)
        C_local = disp["C"]
        Cg_local = disp["Cg"]

        Ks = math.sqrt(Cgo / Cg_local)

        sin_theta = (C_local / Co) * math.sin(theta0)
        sin_theta = max(-1.0, min(1.0, sin_theta))
        theta_local = math.asin(sin_theta)

        if abs(theta0) > 1e-10:
            cos_ratio = math.cos(theta0) / math.cos(theta_local)
            Kr = math.sqrt(max(cos_ratio, 0.0))
        else:
            Kr = 1.0

        H = H0 * Ks * Kr

        results.append({
            "d": d,
            "H": round(H, 6),
            "theta": round(math.degrees(theta_local), 4),
            "Ks": round(Ks, 6),
            "Kr": round(Kr, 6),
        })

    return results


# ---------------------------------------------------------------------------
# Wave breaking
# ---------------------------------------------------------------------------
def compute_breaking(H0, T, beach_slope, Kr=1.0):
    H0_prime = Kr * H0
    Lo = G * T ** 2 / (2.0 * math.pi)

    omega_b = 0.56 * (H0_prime / Lo) ** (-0.2)
    Hb = omega_b * H0_prime

    tan_b = beach_slope
    a_w = 43.8 * (1.0 - math.exp(-19.0 * tan_b))
    b_w = 1.56 / (1.0 + math.exp(-19.5 * tan_b))

    gamma_b = b_w - a_w * Hb / (G * T ** 2)
    db = Hb / gamma_b

    return {"Hb": Hb, "db": db, "gamma_b": gamma_b}


# ---------------------------------------------------------------------------
# Wave setup
# ---------------------------------------------------------------------------
def compute_setup(Hb, db, gamma_b, beach_slope):
    eta_b = -(1.0 / 16.0) * gamma_b ** 2 * db

    factor = 1.0 / (1.0 + 8.0 / (3.0 * gamma_b ** 2))

    hb_total = db - eta_b

    eta_s = eta_b + factor * hb_total

    deta_dx = factor * beach_slope

    denominator = beach_slope - deta_dx
    if abs(denominator) < 1e-12:
        dx = 0.0
    else:
        dx = eta_s / denominator

    eta_max = eta_s + deta_dx * dx

    return {
        "eta_b": eta_b,
        "eta_s": eta_s,
        "eta_max": eta_max,
        "shoreline_displacement_m": dx,
    }


# ---------------------------------------------------------------------------
# Irregular wave runup (Mase 1989)
# ---------------------------------------------------------------------------
def compute_runup(H0, T, beach_slope):
    Lo = G * T ** 2 / (2.0 * math.pi)
    xi_0 = beach_slope / math.sqrt(H0 / Lo)

    Rmax = 2.32 * H0 * xi_0 ** 0.77
    R2pct = 1.86 * H0 * xi_0 ** 0.71
    R_1_10 = 1.70 * H0 * xi_0 ** 0.71
    R_1_3 = 1.38 * H0 * xi_0 ** 0.70
    R_mean = 0.88 * H0 * xi_0 ** 0.69

    return {
        "Rmax": Rmax,
        "R2pct": R2pct,
        "R_1_10": R_1_10,
        "R_1_3": R_1_3,
        "R_mean": R_mean,
    }


# ---------------------------------------------------------------------------
# Overtopping discharge
# ---------------------------------------------------------------------------
def load_owen_coefficients(csv_path="/app/data/owen_coefficients.csv"):
    coeffs = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            coeffs.append({
                "cot_alpha": float(row["cot_alpha"]),
                "a": float(row["a"]),
                "b": float(row["b"]),
            })
    return sorted(coeffs, key=lambda c: c["cot_alpha"])


def interpolate_owen(cot_alpha, coeffs):
    slopes = [c["cot_alpha"] for c in coeffs]

    if cot_alpha <= slopes[0]:
        return coeffs[0]["a"], coeffs[0]["b"]
    if cot_alpha >= slopes[-1]:
        return coeffs[-1]["a"], coeffs[-1]["b"]

    for i in range(len(slopes) - 1):
        if slopes[i] <= cot_alpha <= slopes[i + 1]:
            t = (cot_alpha - slopes[i]) / (slopes[i + 1] - slopes[i])
            a = coeffs[i]["a"] + t * (coeffs[i + 1]["a"] - coeffs[i]["a"])
            b = coeffs[i]["b"] + t * (coeffs[i + 1]["b"] - coeffs[i]["b"])
            return a, b

    return coeffs[-1]["a"], coeffs[-1]["b"]


def compute_overtopping(Hs_toe, Tp, structure):
    cot_alpha = structure["slope_cot"]
    Rc = structure["Rc"]
    gamma_r = structure.get("roughness", 1.0)
    tan_alpha = 1.0 / cot_alpha

    # Owen (1980)
    Tm = 0.8 * Tp
    coeffs = load_owen_coefficients()
    a_owen, b_owen = interpolate_owen(cot_alpha, coeffs)

    R_star = Rc / (gamma_r * Tm * math.sqrt(G * Hs_toe))
    Q_star = a_owen * math.exp(-b_owen * R_star)
    q_owen = Q_star * G * Hs_toe * Tm

    # van der Meer & Janssen (1995)
    Lop = G * Tp ** 2 / (2.0 * math.pi)
    sop = Hs_toe / Lop
    xi_op = tan_alpha / math.sqrt(sop)

    if xi_op <= 2.0:
        Q_vdm = (0.067 / math.sqrt(tan_alpha)) * xi_op * math.exp(
            -4.75 * Rc / (Hs_toe * xi_op * gamma_r)
        )
    else:
        Q_vdm = 0.2 * math.exp(-2.6 * Rc / (Hs_toe * gamma_r))

    q_vdm = Q_vdm * math.sqrt(G * Hs_toe ** 3)

    return {
        "owen": {"q": q_owen},
        "vdm": {"q": q_vdm},
    }


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
def compute_full(scenario):
    H0 = scenario["H0"]
    T = scenario["period"]
    theta0 = scenario.get("theta0", 0.0)
    beach_slope = scenario["beach_slope"]
    Kr_val = scenario.get("Kr", 1.0)
    struct = scenario["structure"]
    dtoe = struct["dtoe"]

    brk = compute_breaking(H0, T, beach_slope, Kr_val)
    stp = compute_setup(brk["Hb"], brk["db"], brk["gamma_b"], beach_slope)
    rnp = compute_runup(H0, T, beach_slope)

    Lo = G * T ** 2 / (2.0 * math.pi)
    Co = Lo / T
    Cgo = Co / 2.0
    disp_toe = solve_dispersion(T, dtoe)
    Ks_toe = math.sqrt(Cgo / disp_toe["Cg"])

    if abs(theta0) > 1e-10:
        sin_theta = (disp_toe["C"] / Co) * math.sin(math.radians(theta0))
        sin_theta = max(-1.0, min(1.0, sin_theta))
        theta_toe = math.asin(sin_theta)
        Kr_toe = math.sqrt(max(math.cos(math.radians(theta0)) / math.cos(theta_toe), 0.0))
    else:
        Kr_toe = 1.0

    Hs_toe = H0 * Ks_toe * Kr_toe

    if dtoe < brk["db"]:
        Hs_toe = min(Hs_toe, brk["gamma_b"] * dtoe)

    ovt = compute_overtopping(Hs_toe, T, struct)
    twl = stp["eta_max"] + rnp["R2pct"]

    return {
        "breaking": brk,
        "setup": stp,
        "runup": rnp,
        "overtopping": ovt,
        "total_water_level": twl,
    }


# ---------------------------------------------------------------------------
# Main CLI entry point
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: coastal_pipeline.py <scenario.json>", file=sys.stderr)
        sys.exit(1)

    scenario_path = sys.argv[1]
    with open(scenario_path) as f:
        scenario = json.load(f)

    mode = scenario["mode"]

    if mode == "dispersion":
        T = scenario["period"]
        depths = scenario["depths"]
        results = [solve_dispersion(T, d) for d in depths]
        output = {"results": results}

    elif mode == "transect":
        results = compute_transect(
            scenario["H0"],
            scenario["period"],
            scenario.get("theta0", 0.0),
            scenario["depths"],
        )
        output = {"results": results}

    elif mode == "breaking":
        output = compute_breaking(
            scenario["H0"],
            scenario["period"],
            scenario["beach_slope"],
            scenario.get("Kr", 1.0),
        )

    elif mode == "setup":
        output = compute_setup(
            scenario["Hb"],
            scenario["db"],
            scenario["gamma_b"],
            scenario["beach_slope"],
        )

    elif mode == "runup":
        output = compute_runup(
            scenario["H0"],
            scenario["period"],
            scenario["beach_slope"],
        )

    elif mode == "overtopping":
        output = compute_overtopping(
            scenario["Hs_toe"],
            scenario["Tp"],
            scenario["structure"],
        )

    elif mode == "full":
        output = compute_full(scenario)

    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)

    output_json = json.dumps(output, indent=2)
    print(output_json)

    # Store result in SQLite
    try:
        conn = init_db()
        scenario_name = os.path.splitext(os.path.basename(scenario_path))[0]
        save_result(conn, scenario_name, mode, json.dumps(scenario), output_json)
        conn.close()
    except Exception:
        pass  # Don't fail if DB write fails


if __name__ == "__main__":
    main()
