#!/usr/bin/env python3
"""
CFD Flat Plate Benchmark Analysis — solution pipeline.
Produces results.json, convergence.eps (gnuplot), and benchmark.db (SQLite).
"""

import json
import math
import os
import sqlite3
import subprocess

import numpy as np

DATA_DIR = "/app/data"


# ============================================================
# PLOT2D Grid Parser
# ============================================================

def parse_plot2d_grid(filepath):
    with open(filepath) as f:
        lines = f.readlines()

    nzones = int(lines[0].strip())
    dims = lines[1].split()
    nx, ny = int(dims[0]), int(dims[1])
    n_total = nx * ny

    values = []
    for line in lines[2:]:
        for token in line.split():
            values.append(float(token))

    x_coords = np.array(values[:n_total]).reshape(ny, nx)
    y_coords = np.array(values[n_total:2 * n_total]).reshape(ny, nx)

    return nx, ny, x_coords, y_coords


def compute_grid_metrics(nx, ny, x_grid, y_grid):
    plate_col = None
    for i in range(nx):
        if x_grid[0, i] > 0.01 and x_grid[0, i] < 1.9:
            plate_col = i
            break

    y_wall_normal = y_grid[:, plate_col]
    y1 = float(y_wall_normal[1] - y_wall_normal[0])

    dy = np.diff(y_wall_normal)
    positive = dy[:-1] > 0
    stretch_ratios = dy[1:][positive] / dy[:-1][positive]
    max_stretch = float(np.max(stretch_ratios))

    return {
        "nx": nx,
        "ny": ny,
        "y1": y1,
        "max_stretch_ratio": round(max_stretch, 6),
    }


# ============================================================
# Tecplot ASCII Parser
# ============================================================

def parse_tecplot_zones(filepath):
    zones = []
    current_zone = None
    var_names = None

    with open(filepath, "rb") as f:
        content = f.read().decode("utf-8", errors="replace")

    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower.startswith("variables"):
            var_part = line.split("=", 1)[1]
            var_names = [v.strip().strip('"') for v in var_part.split(",")]
            continue
        if "zone" in lower.split(",")[0].lower() or lower.startswith("zone"):
            title = ""
            if "t=" in lower:
                idx = lower.index("t=")
                title = line[idx + 2:].strip().strip('"')
            current_zone = {"title": title, "data": [], "vars": var_names}
            zones.append(current_zone)
            continue
        if current_zone is not None:
            parts = line.split()
            try:
                row = tuple(float(x) for x in parts)
                if len(row) > 0:
                    current_zone["data"].append(row)
            except ValueError:
                continue

    return zones


# ============================================================
# Richardson Extrapolation
# ============================================================

def richardson_extrapolation(data_rows):
    f1, f2, f3 = data_rows[0][2], data_rows[1][2], data_rows[2][2]
    h1, h2, h3 = data_rows[0][1], data_rows[1][1], data_rows[2][1]

    r21 = h2 / h1
    r32 = h3 / h2

    eps21 = f2 - f1
    eps32 = f3 - f2

    monotonic = (eps32 * eps21) > 0
    s = 1.0 if (eps32 / eps21) > 0 else -1.0

    p = abs(math.log(abs(eps32 / eps21))) / math.log(r21)
    for _ in range(100):
        try:
            q = math.log(abs((r21**p - s) / (r32**p - s)))
        except (ValueError, ZeroDivisionError):
            break
        p_new = (1.0 / math.log(r21)) * abs(math.log(abs(eps32 / eps21)) + q)
        if abs(p_new - p) < 1e-14:
            break
        p = p_new

    f_ext = (r21**p * f1 - f2) / (r21**p - 1.0)

    e_a = abs((f1 - f2) / f1)
    e_a_pct = e_a * 100.0

    Fs = 1.25
    gci = Fs * e_a / (r21**p - 1.0)
    gci_pct = gci * 100.0

    return {
        "p": round(p, 6),
        "f_ext": f_ext,
        "e_a_pct": round(e_a_pct, 6),
        "gci_pct": round(gci_pct, 6),
        "monotonic": monotonic,
    }


def parse_convergence_file(filepath):
    zones = parse_tecplot_zones(filepath)
    result = {}
    for i, z in enumerate(zones):
        rows = []
        for row in z["data"]:
            N = row[0]
            h = row[2]
            f = row[3]
            rows.append((N, h, f))
        key = f"zone{i + 1}"
        result[key] = rows
    return result


# ============================================================
# Boundary Layer Analysis
# ============================================================

def compute_boundary_layer(u_data, y_data):
    u_arr = np.array(u_data)
    y_arr = np.array(y_data)
    u_e = float(np.max(u_arr))
    u99 = 0.99 * u_e

    delta99 = None
    for i in range(len(u_arr) - 1):
        if u_arr[i] <= u99 and u_arr[i + 1] >= u99:
            frac = (u99 - u_arr[i]) / (u_arr[i + 1] - u_arr[i])
            delta99 = float(y_arr[i] + frac * (y_arr[i + 1] - y_arr[i]))
            break
    if delta99 is None:
        delta99 = float(y_arr[-1])

    cutoff = 5.0 * delta99
    mask = y_arr <= cutoff
    u_cut = u_arr[mask]
    y_cut = y_arr[mask]

    delta_star = float(np.trapz(1.0 - u_cut / u_e, y_cut))
    theta = float(np.trapz((u_cut / u_e) * (1.0 - u_cut / u_e), y_cut))

    H = delta_star / theta if theta > 0 else 0.0
    return {
        "delta99": delta99,
        "delta_star": delta_star,
        "theta": theta,
        "H": round(H, 6),
    }


# ============================================================
# Law-of-the-Wall Analysis
# ============================================================

def analyze_log_law(logy_data, uplus_data):
    log_law_logy = []
    log_law_up = []
    for ly, up in zip(logy_data, uplus_data):
        yp = 10.0**ly
        if 50.0 <= yp <= 500.0:
            log_law_logy.append(ly)
            log_law_up.append(up)

    n = len(log_law_logy)
    if n < 3:
        return {"kappa_fit": 0.0, "B_fit": 0.0, "rms_standard": 0.0}

    ln10 = math.log(10.0)
    ln_yp = np.array([ln10 * ly for ly in log_law_logy])
    up_arr = np.array(log_law_up)

    # Least-squares fit: u+ = (1/kappa)*ln(y+) + B
    A = np.column_stack([ln_yp, np.ones(n)])
    coeffs = np.linalg.lstsq(A, up_arr, rcond=None)[0]
    a, b = coeffs[0], coeffs[1]

    kappa_fit = 1.0 / a
    B_fit = b

    kappa_std = 0.41
    B_std = 5.0
    rms_sq = 0.0
    for ly, up in zip(log_law_logy, log_law_up):
        yp = 10.0**ly
        up_std = (1.0 / kappa_std) * math.log(yp) + B_std
        rms_sq += (up - up_std) ** 2
    rms_standard = math.sqrt(rms_sq / n)

    return {
        "kappa_fit": round(kappa_fit, 6),
        "B_fit": round(B_fit, 6),
        "rms_standard": round(rms_standard, 6),
    }


# ============================================================
# Eddy Viscosity Analysis
# ============================================================

def analyze_eddy_viscosity(y_data, mut_data):
    mut_arr = np.array(mut_data)
    peak_idx = int(np.argmax(mut_arr))
    peak_val = float(mut_arr[peak_idx])

    monotonic = True
    for i in range(peak_idx):
        if mut_arr[i + 1] < mut_arr[i]:
            monotonic = False
            break

    return {
        "peak_mut": round(peak_val, 4),
        "peak_y": y_data[peak_idx],
        "monotonic_to_peak": monotonic,
    }


# ============================================================
# Gnuplot Convergence Plot
# ============================================================

def generate_convergence_plot(cf_data, results):
    os.makedirs("/app/plots", exist_ok=True)

    with open("/tmp/cfl3d_cf.dat", "w") as f:
        for row in cf_data["zone1"]:
            f.write(f"{row[1]:.10e} {row[2]:.12e}\n")

    with open("/tmp/fun3d_cf.dat", "w") as f:
        for row in cf_data["zone2"]:
            f.write(f"{row[1]:.10e} {row[2]:.12e}\n")

    cfl3d_ext = results["convergence"]["cfl3d_cf"]["f_ext"]
    fun3d_ext = results["convergence"]["fun3d_cf"]["f_ext"]

    gnuplot_script = f"""set terminal postscript eps enhanced color font "Helvetica,14"
set output '/app/plots/convergence.eps'
set xlabel 'Grid spacing h'
set ylabel 'Skin friction coefficient C_f'
set logscale x
set title 'Grid Convergence: Flat Plate Skin Friction'
set key top left box
set format x "10^{{%L}}"
plot '/tmp/cfl3d_cf.dat' using 1:2 title 'CFL3D' with linespoints pt 7 ps 1.5 lw 2, \\
     '/tmp/fun3d_cf.dat' using 1:2 title 'FUN3D' with linespoints pt 5 ps 1.5 lw 2, \\
     {cfl3d_ext:.10e} title 'CFL3D extrapolated' with lines lt 1 lw 1 dt 2, \\
     {fun3d_ext:.10e} title 'FUN3D extrapolated' with lines lt 2 lw 1 dt 2
"""

    with open("/tmp/convergence.gp", "w") as f:
        f.write(gnuplot_script)

    subprocess.run(["gnuplot", "/tmp/convergence.gp"], check=True)


# ============================================================
# SQLite Database
# ============================================================

def create_database(cf_data, cd_data, u_values, y_values, results):
    db_path = "/app/benchmark.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # convergence_raw
    c.execute("""CREATE TABLE convergence_raw (
        code TEXT, quantity TEXT, grid_n REAL, grid_h REAL, value REAL
    )""")
    for row in cf_data["zone1"]:
        c.execute("INSERT INTO convergence_raw VALUES (?,?,?,?,?)",
                  ("CFL3D", "cf", row[0], row[1], row[2]))
    for row in cf_data["zone2"]:
        c.execute("INSERT INTO convergence_raw VALUES (?,?,?,?,?)",
                  ("FUN3D", "cf", row[0], row[1], row[2]))
    for row in cd_data["zone1"]:
        c.execute("INSERT INTO convergence_raw VALUES (?,?,?,?,?)",
                  ("CFL3D", "cd", row[0], row[1], row[2]))
    for row in cd_data["zone2"]:
        c.execute("INSERT INTO convergence_raw VALUES (?,?,?,?,?)",
                  ("FUN3D", "cd", row[0], row[1], row[2]))

    # convergence_results
    c.execute("""CREATE TABLE convergence_results (
        code TEXT, quantity TEXT, p REAL, f_ext REAL,
        e_a_pct REAL, gci_pct REAL, monotonic INTEGER
    )""")
    mapping = [
        ("cfl3d_cf", "CFL3D", "cf"), ("fun3d_cf", "FUN3D", "cf"),
        ("cfl3d_cd", "CFL3D", "cd"), ("fun3d_cd", "FUN3D", "cd"),
    ]
    for key, code, qty in mapping:
        r = results["convergence"][key]
        c.execute("INSERT INTO convergence_results VALUES (?,?,?,?,?,?,?)",
                  (code, qty, r["p"], r["f_ext"], r["e_a_pct"], r["gci_pct"],
                   1 if r["monotonic"] else 0))

    # boundary_layer_profile
    c.execute("CREATE TABLE boundary_layer_profile (u REAL, y REAL)")
    for u, y in zip(u_values, y_values):
        c.execute("INSERT INTO boundary_layer_profile VALUES (?,?)", (u, y))

    # analysis_summary
    c.execute("""CREATE TABLE analysis_summary (
        result_name TEXT, result_value REAL
    )""")
    summaries = []
    g = results["grid"]
    summaries.append(("grid_nx", g["nx"]))
    summaries.append(("grid_ny", g["ny"]))
    summaries.append(("grid_y1", g["y1"]))
    summaries.append(("grid_max_stretch_ratio", g["max_stretch_ratio"]))
    bl = results["boundary_layer"]
    summaries.append(("delta99", bl["delta99"]))
    summaries.append(("delta_star", bl["delta_star"]))
    summaries.append(("theta", bl["theta"]))
    summaries.append(("shape_factor_H", bl["H"]))
    ll = results["log_law"]
    summaries.append(("kappa_fit", ll["kappa_fit"]))
    summaries.append(("B_fit", ll["B_fit"]))
    summaries.append(("rms_standard", ll["rms_standard"]))
    ev = results["eddy_viscosity"]
    summaries.append(("peak_mut", ev["peak_mut"]))
    summaries.append(("peak_y", ev["peak_y"]))
    for name, val in summaries:
        c.execute("INSERT INTO analysis_summary VALUES (?,?)", (name, val))

    conn.commit()
    conn.close()


# ============================================================
# Main
# ============================================================

def main():
    results = {}

    # Grid analysis
    grid_file = os.path.join(DATA_DIR, "flatplate_35x25.p2dfmt")
    nx, ny, x_grid, y_grid = parse_plot2d_grid(grid_file)
    results["grid"] = compute_grid_metrics(nx, ny, x_grid, y_grid)

    # Grid convergence analysis
    cf_data = parse_convergence_file(os.path.join(DATA_DIR, "cf_convergence.dat"))
    cd_data = parse_convergence_file(os.path.join(DATA_DIR, "drag_convergence.dat"))
    results["convergence"] = {
        "cfl3d_cf": richardson_extrapolation(cf_data["zone1"]),
        "fun3d_cf": richardson_extrapolation(cf_data["zone2"]),
        "cfl3d_cd": richardson_extrapolation(cd_data["zone1"]),
        "fun3d_cd": richardson_extrapolation(cd_data["zone2"]),
    }

    # Boundary layer (first zone of flatplate_u.dat)
    u_zones = parse_tecplot_zones(os.path.join(DATA_DIR, "flatplate_u.dat"))
    zone1 = u_zones[0]
    u_values = [row[0] for row in zone1["data"]]
    y_values = [row[1] for row in zone1["data"]]
    results["boundary_layer"] = compute_boundary_layer(u_values, y_values)

    # Log-law (first zone of u+y+)
    upy_zones = parse_tecplot_zones(os.path.join(DATA_DIR, "flatplate_u+y+.dat"))
    zone1_upy = upy_zones[0]
    logy_data = [row[0] for row in zone1_upy["data"]]
    uplus_data = [row[1] for row in zone1_upy["data"]]
    results["log_law"] = analyze_log_law(logy_data, uplus_data)

    # Eddy viscosity (CFL3D zone of mut_0.97.dat)
    mut_zones = parse_tecplot_zones(os.path.join(DATA_DIR, "mut_0.97.dat"))
    mut_zone = mut_zones[0]
    mut_y = [row[1] for row in mut_zone["data"]]
    mut_v = [row[2] for row in mut_zone["data"]]
    results["eddy_viscosity"] = analyze_eddy_viscosity(mut_y, mut_v)

    # Write results.json
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Generate gnuplot convergence plot
    generate_convergence_plot(cf_data, results)

    # Create SQLite database
    create_database(cf_data, cd_data, u_values, y_values, results)

    print("Analysis complete. Deliverables: results.json, plots/convergence.eps, benchmark.db")


if __name__ == "__main__":
    main()
