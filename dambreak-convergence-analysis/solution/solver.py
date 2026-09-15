#!/usr/bin/env python3
"""
Analytical dam break solution on inclined plane with Coulomb friction.
Produces ESRI ASCII rasters, GeoTIFF copies via GDAL, and stores
convergence and energy-line analyses in a SQLite database.
"""

import configparser
import math
import os
import sqlite3
import subprocess

import numpy as np


# ------------------------------------------------------------------ #
#  Config parsing                                                      #
# ------------------------------------------------------------------ #

def load_config(path="/app/dambreak.ini"):
    cfg = configparser.ConfigParser()
    cfg.read(path)

    def plist(s):
        return [float(x.strip()) for x in s.split("|")]

    return {
        "slope_angle_deg": cfg.getfloat("DAMBREAK", "slopeAngleDeg"),
        "friction_angle_deg": cfg.getfloat("DAMBREAK", "frictionAngleDeg"),
        "initial_height_m": cfg.getfloat("DAMBREAK", "initialHeightM"),
        "initial_column_x_min_m": cfg.getfloat("DAMBREAK", "columnXMinM"),
        "initial_column_x_max_m": cfg.getfloat("DAMBREAK", "columnXMaxM"),
        "earth_pressure_coeff": cfg.getfloat("DAMBREAK", "earthPressureCoeff"),
        "density_kg_m3": cfg.getfloat("DAMBREAK", "densityKgM3"),
        "gravity_m_s2": cfg.getfloat("GENERAL", "gravityMS2"),
        "time_steps_s": plist(cfg.get("OUTPUT", "timeStepsS")),
        "grid_resolutions_m": plist(cfg.get("OUTPUT", "gridResolutionsM")),
        "domain_x_min_m": cfg.getfloat("OUTPUT", "domainXMinM"),
        "domain_x_max_m": cfg.getfloat("OUTPUT", "domainXMaxM"),
        "domain_y_min_m": cfg.getfloat("OUTPUT", "domainYMinM"),
        "domain_y_max_m": cfg.getfloat("OUTPUT", "domainYMaxM"),
    }


# ------------------------------------------------------------------ #
#  Physics                                                             #
# ------------------------------------------------------------------ #

def derive_physics(cfg):
    phi = math.radians(cfg["slope_angle_deg"])
    delta = math.radians(cfg["friction_angle_deg"])
    h0 = cfg["initial_height_m"]
    Kx = cfg["earth_pressure_coeff"]
    g = cfg["gravity_m_s2"]
    rho = cfg["density_kg_m3"]
    x_col_min = cfg["initial_column_x_min_m"]
    x_col_max = cfg["initial_column_x_max_m"]

    g_eff = Kx * g * math.cos(phi)
    mu = math.tan(delta)
    a_net = g * (math.sin(phi) - mu * math.cos(phi))
    c0 = math.sqrt(g_eff * h0)

    return dict(
        phi=phi, delta=delta, h0=h0, Kx=Kx, g=g, rho=rho,
        g_eff=g_eff, mu=mu, a_net=a_net, c0=c0,
        x_col_min=x_col_min, x_col_max=x_col_max,
    )


# ------------------------------------------------------------------ #
#  Analytical solution (vectorised over x)                             #
# ------------------------------------------------------------------ #

def analytical_fields(x_arr, t, p):
    """Return (h, u) arrays for a 1-D array of x positions at time t."""
    h0 = p["h0"]
    c0 = p["c0"]
    a = p["a_net"]
    g_eff = p["g_eff"]
    x_col_min = p["x_col_min"]

    half_at2 = 0.5 * a * t * t

    x_left = x_col_min + half_at2
    x_A = -c0 * t + half_at2
    x_B = 2.0 * c0 * t + half_at2

    h = np.zeros_like(x_arr)
    u = np.zeros_like(x_arr)

    mask_und = (x_arr >= x_left) & (x_arr <= x_A)
    h[mask_und] = h0
    u[mask_und] = a * t

    mask_rar = (x_arr > x_A) & (x_arr <= x_B)
    xi = (x_arr[mask_rar] - half_at2) / t
    h[mask_rar] = (2.0 * c0 - xi) ** 2 / (9.0 * g_eff)
    u[mask_rar] = (2.0 / 3.0) * (xi + c0) + a * t

    return h, u


# ------------------------------------------------------------------ #
#  ESRI ASCII I/O                                                      #
# ------------------------------------------------------------------ #

def write_asc(filepath, data, xllcorner, yllcorner, cellsize, nodata=-9999):
    nrows, ncols = data.shape
    with open(filepath, "w") as fh:
        fh.write(f"ncols {ncols}\n")
        fh.write(f"nrows {nrows}\n")
        fh.write(f"xllcorner {xllcorner}\n")
        fh.write(f"yllcorner {yllcorner}\n")
        fh.write(f"cellsize {cellsize}\n")
        fh.write(f"NODATA_value {nodata}\n")
        for row in data:
            fh.write(" ".join(f"{v:.6f}" for v in row))
            fh.write("\n")


# ------------------------------------------------------------------ #
#  GeoTIFF conversion                                                  #
# ------------------------------------------------------------------ #

def asc_to_geotiff(asc_path, tif_path):
    subprocess.run(
        ["gdal_translate", "-of", "GTiff", "-q", asc_path, tif_path],
        check=True, capture_output=True
    )


# ------------------------------------------------------------------ #
#  Main pipeline                                                       #
# ------------------------------------------------------------------ #

def generate_rasters(cfg, phys):
    """Generate all ASC rasters and GeoTIFF copies."""
    x_min = cfg["domain_x_min_m"]
    x_max = cfg["domain_x_max_m"]
    y_min = cfg["domain_y_min_m"]
    y_max = cfg["domain_y_max_m"]

    store = {}

    for res in cfg["grid_resolutions_m"]:
        ncols = int(round((x_max - x_min) / res))
        nrows = int(round((y_max - y_min) / res))

        rs = f"{int(res)}m" if res == int(res) else f"{res}m"
        out_dir = f"/app/output/{rs}"
        os.makedirs(out_dir, exist_ok=True)

        x_centers = x_min + (np.arange(ncols) + 0.5) * res

        for t in cfg["time_steps_s"]:
            h_row, u_row = analytical_fields(x_centers, t, phys)

            h_2d = np.tile(h_row, (nrows, 1))
            u_2d = np.tile(u_row, (nrows, 1))

            ts = f"{int(t)}s" if t == int(t) else f"{t}s"

            asc_h = f"{out_dir}/pft_t{ts}.asc"
            asc_v = f"{out_dir}/pfv_t{ts}.asc"
            write_asc(asc_h, h_2d, x_min, y_min, res)
            write_asc(asc_v, u_2d, x_min, y_min, res)

            asc_to_geotiff(asc_h, f"{out_dir}/pft_t{ts}.tif")
            asc_to_geotiff(asc_v, f"{out_dir}/pfv_t{ts}.tif")

            store[(res, t)] = (h_2d, u_2d, x_centers)

    return store


def build_sqlite(cfg, store, phys):
    """Build the results SQLite database with convergence and energy_line tables."""
    db_path = "/app/output/results.db"

    # Remove existing database to ensure idempotent runs
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)

    # --- Convergence table ---
    conn.execute(
        "CREATE TABLE convergence ("
        "coarse_m REAL, fine_m REAL, time_s REAL, "
        "l2_pft REAL, lmax_pft REAL)"
    )

    resolutions = sorted(cfg["grid_resolutions_m"], reverse=True)
    for i in range(len(resolutions) - 1):
        rc = resolutions[i]
        rf = resolutions[i + 1]
        for t in cfg["time_steps_s"]:
            _, _, xc = store[(rc, t)]
            h_fine, _, xf = store[(rf, t)]

            h_c_row = store[(rc, t)][0][0]
            h_f_row = h_fine[0]

            h_c_interp = np.interp(xf, xc, h_c_row)
            diff = h_f_row - h_c_interp
            l2 = float(np.sqrt(np.mean(diff ** 2)))
            lmax = float(np.max(np.abs(diff)))

            conn.execute(
                "INSERT INTO convergence VALUES (?, ?, ?, ?, ?)",
                (rc, rf, t, round(l2, 8), round(lmax, 8))
            )

    # --- Energy line table ---
    conn.execute(
        "CREATE TABLE energy_line (key TEXT PRIMARY KEY, value REAL)"
    )

    r_fine = min(cfg["grid_resolutions_m"])
    t_last = max(cfg["time_steps_s"])

    h_2d, u_2d, x_centers = store[(r_fine, t_last)]
    dx = r_fine
    h_row = h_2d[0]
    u_row = u_2d[0]

    total_h_dx = float(np.sum(h_row) * dx)

    x_cm = float(np.sum(h_row * x_centers * dx)) / total_h_dx
    v2_avg = float(np.sum(h_row * u_row ** 2 * dx)) / total_h_dx

    phi = phys["phi"]
    g = phys["g"]

    z_cm = -x_cm * math.sin(phi)
    s_cm = x_cm * math.cos(phi)
    kinetic_alt = v2_avg / (2.0 * g)

    x_cm_0 = (phys["x_col_min"] + phys["x_col_max"]) / 2.0
    z_cm_0 = -x_cm_0 * math.sin(phi)
    s_cm_0 = x_cm_0 * math.cos(phi)

    ds = s_cm - s_cm_0
    dz = z_cm_0 - z_cm - kinetic_alt
    tan_alpha = dz / ds if abs(ds) > 1e-12 else 0.0
    alpha_deg = math.degrees(math.atan(tan_alpha))

    entries = [
        ("runout_angle_deg", round(alpha_deg, 4)),
        ("theoretical_alpha_deg", cfg["friction_angle_deg"]),
        ("mass_center_x_m", round(x_cm, 4)),
        ("mass_center_z_m", round(z_cm, 4)),
        ("kinetic_altitude_m", round(kinetic_alt, 4)),
    ]
    conn.executemany("INSERT INTO energy_line VALUES (?, ?)", entries)

    conn.commit()
    conn.close()


def main():
    cfg = load_config()
    phys = derive_physics(cfg)

    os.makedirs("/app/output", exist_ok=True)

    store = generate_rasters(cfg, phys)
    build_sqlite(cfg, store, phys)

    print("Dam break analysis complete.")


if __name__ == "__main__":
    main()
