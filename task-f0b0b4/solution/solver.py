#!/usr/bin/env python3
"""
CFD Solver Verification Audit — reference solution.

Parses NASA TMR Tecplot data, performs grid convergence analysis,
boundary layer evaluation, wall-law assessment, generates gnuplot
plots, and writes the structured report.
"""

import json
import math
import os
import subprocess

import numpy as np

DATA_DIR = "/app/data"
OUTPUT_PATH = "/app/report.json"


# ─── Tecplot Parsing ───────────────────────────────────────────────────────

def parse_tecplot_zones(filepath):
    """Parse a multi-zone Tecplot ASCII file.
    Returns dict: zone_name -> list of rows (each row is list of floats).
    """
    zones = {}
    current_zone = None
    current_data = []

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith("variables"):
                continue
            if stripped.lower().startswith("zone"):
                if current_zone is not None:
                    zones[current_zone] = current_data
                title = ""
                if '"' in stripped:
                    start = stripped.index('"') + 1
                    end = stripped.rindex('"')
                    title = stripped[start:end].strip()
                current_zone = title
                current_data = []
                continue
            try:
                values = [float(x) for x in stripped.split()]
                current_data.append(values)
            except ValueError:
                continue

    if current_zone is not None:
        zones[current_zone] = current_data
    return zones


# ─── Grid Convergence Analysis ─────────────────────────────────────────────

def compute_convergence(f1, f2, f3, r21=2.0, r32=2.0):
    """Compute apparent order, extrapolated value, and uncertainty
    from three grid levels using Richardson extrapolation with GCI."""
    eps21 = f2 - f1
    eps32 = f3 - f2

    ratio = eps32 / eps21
    s = 1.0 if ratio > 0 else -1.0

    if abs(r21 - r32) < 1e-10:
        p = math.log(abs(ratio)) / math.log(r21)
    else:
        p = math.log(abs(ratio)) / math.log(r21)
        for _ in range(50):
            q = math.log((r21**p - s) / (r32**p - s))
            p_new = (1.0 / math.log(r21)) * abs(math.log(abs(ratio)) + q)
            if abs(p_new - p) < 1e-10:
                break
            p = p_new

    rp = r21**p
    f_ext = (rp * f1 - f2) / (rp - 1.0)

    e_ext21 = abs((f_ext - f1) / f_ext) * 100.0
    uncertainty = 1.25 * e_ext21

    return {
        "observed_order": round(p, 4),
        "fine_grid_uncertainty_pct": round(uncertainty, 4),
        "extrapolated_value": round(f_ext, 7),
    }


def classify_order(p):
    if p >= 1.5:
        return "nominal"
    elif p >= 0.5:
        return "degraded"
    else:
        return "anomalous"


def run_grid_convergence():
    cf_data = parse_tecplot_zones(os.path.join(DATA_DIR, "cf_convergence.dat"))
    cd_data = parse_tecplot_zones(os.path.join(DATA_DIR, "drag_convergence.dat"))

    results = {}

    for label, zones in [("cf", cf_data), ("cd", cd_data)]:
        for zone_name, rows in zones.items():
            code = zone_name.lower().replace(" ", "")
            case_key = f"{label}_{code}"

            f1 = rows[0][3]
            f2 = rows[1][3]
            f3 = rows[2][3]

            h1 = rows[0][2]
            h2 = rows[1][2]
            h3 = rows[2][2]
            r21 = h2 / h1
            r32 = h3 / h2

            gc = compute_convergence(f1, f2, f3, r21, r32)
            gc["order_verdict"] = classify_order(gc["observed_order"])
            results[case_key] = gc

    return results


# ─── Solver Ranking ────────────────────────────────────────────────────────

def compute_solver_ranking(gc):
    ranking = {}
    for qty, prefix in [("skin_friction", "cf"), ("drag", "cd")]:
        u_cfl3d = gc[f"{prefix}_cfl3d"]["fine_grid_uncertainty_pct"]
        u_fun3d = gc[f"{prefix}_fun3d"]["fine_grid_uncertainty_pct"]
        ranking[qty] = "cfl3d" if u_cfl3d <= u_fun3d else "fun3d"
    return ranking


# ─── Publication Readiness ─────────────────────────────────────────────────

def compute_publication_ready(gc):
    ready = {}
    for case in ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"]:
        u = gc[case]["fine_grid_uncertainty_pct"]
        p = gc[case]["observed_order"]
        ready[case] = u < 1.0 and p >= 0.5
    return ready


# ─── Boundary Layer Analysis ──────────────────────────────────────────────

def run_boundary_layer():
    zones = parse_tecplot_zones(os.path.join(DATA_DIR, "flatplate_u.dat"))
    zone_name = list(zones.keys())[0]
    rows = zones[zone_name]

    u = np.array([r[0] for r in rows])
    y = np.array([r[1] for r in rows])

    n_outer = min(50, len(u) // 4)
    U_e = np.mean(u[-n_outer:])

    # delta_99
    target = 0.99 * U_e
    delta_99 = y[-1]
    for i in range(1, len(u)):
        if u[i] >= target:
            delta_99 = y[i-1] + (y[i] - y[i-1]) * (target - u[i-1]) / (u[i] - u[i-1])
            break

    _trapz = getattr(np, "trapezoid", np.trapz)

    integrand_star = 1.0 - u / U_e
    displacement_thickness = float(_trapz(integrand_star, y))

    u_ratio = u / U_e
    integrand_theta = u_ratio * (1.0 - u_ratio)
    momentum_thickness = float(_trapz(integrand_theta, y))

    shape_factor = displacement_thickness / momentum_thickness

    Re_per_unit = 5.0e6
    re_theta = U_e * momentum_thickness * Re_per_unit

    dudy_wall = (u[1] - u[0]) / (y[1] - y[0])
    wall_cf = 2.0 * dudy_wall / Re_per_unit

    physically_consistent = 1.2 <= shape_factor <= 1.5

    return {
        "delta_99": round(float(delta_99), 6),
        "displacement_thickness": round(float(displacement_thickness), 6),
        "momentum_thickness": round(float(momentum_thickness), 6),
        "shape_factor": round(float(shape_factor), 4),
        "re_theta": round(float(re_theta), 1),
        "wall_cf": round(float(wall_cf), 6),
        "physically_consistent": physically_consistent,
    }


# ─── Wall-Law Fit ─────────────────────────────────────────────────────────

def spalding_yplus(uplus, kappa=0.41, B=5.0):
    ku = kappa * uplus
    return uplus + np.exp(-kappa * B) * (
        np.exp(ku) - 1.0 - ku - ku**2 / 2.0 - ku**3 / 6.0
    )


def run_wall_law_fit():
    zones = parse_tecplot_zones(os.path.join(DATA_DIR, "flatplate_uplus_yplus.dat"))
    zone_name = list(zones.keys())[0]
    rows = zones[zone_name]

    log10_yp = np.array([r[0] for r in rows])
    up = np.array([r[1] for r in rows])

    log10_30 = np.log10(30.0)
    log10_300 = np.log10(300.0)
    mask = (log10_yp > log10_30) & (log10_yp < log10_300)

    log10_yp_ll = log10_yp[mask]
    up_ll = up[mask]

    yp_spalding = spalding_yplus(up_ll)
    log10_yp_spalding = np.log10(yp_spalding)

    deviation = log10_yp_ll - log10_yp_spalding
    rms = float(np.sqrt(np.mean(deviation**2)))
    maxd = float(np.max(np.abs(deviation)))
    n = int(np.sum(mask))

    if rms < 0.02:
        quality = "excellent"
    elif rms < 0.05:
        quality = "good"
    elif rms < 0.10:
        quality = "acceptable"
    else:
        quality = "poor"

    return {
        "rms_deviation": round(rms, 6),
        "max_deviation": round(maxd, 6),
        "num_points": n,
        "log_layer_quality": quality,
    }


# ─── Gnuplot Convergence Plots ────────────────────────────────────────────

def generate_gnuplot_data(gc_results):
    """Write gnuplot-compatible data files for convergence plotting."""
    cf_data = parse_tecplot_zones(os.path.join(DATA_DIR, "cf_convergence.dat"))
    cd_data = parse_tecplot_zones(os.path.join(DATA_DIR, "drag_convergence.dat"))

    for label, zones in [("cf", cf_data), ("cd", cd_data)]:
        for zone_name, rows in zones.items():
            code = zone_name.lower().replace(" ", "")
            fpath = f"/app/gnuplot_{label}_{code}.dat"
            with open(fpath, "w") as f:
                f.write("# h  value\n")
                for row in rows:
                    f.write(f"{row[2]:.8e}  {row[3]:.12e}\n")

    for label, title, ylabel in [
        ("cf", "Skin Friction Coefficient Grid Convergence", "C_f at x=0.97"),
        ("cd", "Integrated Drag Coefficient Grid Convergence", "C_D"),
    ]:
        ext_cfl3d = gc_results[f"{label}_cfl3d"]["extrapolated_value"]
        ext_fun3d = gc_results[f"{label}_fun3d"]["extrapolated_value"]

        script = f"""set terminal svg size 900,600 font "Arial,12"
set output '/app/plot_{label}.svg'
set title '{title}'
set xlabel 'Grid spacing h = sqrt(1/N)'
set ylabel '{ylabel}'
set key top left
set logscale x
set format x "10^{{%T}}"
set grid

plot '/app/gnuplot_{label}_cfl3d.dat' using 1:2 with linespoints pt 7 ps 1.2 lw 2 title 'CFL3D', \\
     '/app/gnuplot_{label}_fun3d.dat' using 1:2 with linespoints pt 5 ps 1.2 lw 2 title 'FUN3D', \\
     {ext_cfl3d:.12e} with lines dt 2 lw 1 lc rgb "blue" title 'CFL3D extrapolated', \\
     {ext_fun3d:.12e} with lines dt 2 lw 1 lc rgb "red" title 'FUN3D extrapolated'
"""
        script_path = f"/app/gnuplot_{label}.gp"
        with open(script_path, "w") as f:
            f.write(script)

        subprocess.run(["gnuplot", script_path], check=True)


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    gc = run_grid_convergence()
    ranking = compute_solver_ranking(gc)
    pub_ready = compute_publication_ready(gc)
    bl = run_boundary_layer()
    wl = run_wall_law_fit()

    generate_gnuplot_data(gc)

    report = {
        "grid_convergence": gc,
        "solver_ranking": ranking,
        "boundary_layer": bl,
        "wall_law_fit": wl,
        "publication_ready": pub_ready,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {OUTPUT_PATH}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
