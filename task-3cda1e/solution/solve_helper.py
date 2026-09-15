
"""
Solution: Geodetic gravity survey processing pipeline.
Coordinate projection (PROJ), normal gravity (Somigliana), density inversion,
GMT gridding and gradient, Laplace verification.
"""

import csv
import json
import math
import subprocess
import sys
import tempfile

import numpy as np
from scipy.linalg import lstsq

# ============================================================================
# Constants
# ============================================================================

G = 6.6743e-11

# GRS80 parameters
A_E = 6378137.0
F_E = 1.0 / 298.257222101
B_E = A_E * (1 - F_E)
GM_E = 3986005.0e8
OMEGA_E = 7292115e-11
E2 = 2 * F_E - F_E**2
E_LIN = math.sqrt(A_E**2 - B_E**2)
E_PRIME = E_LIN / B_E

# ============================================================================
# Normal gravity (Somigliana equation for GRS80)
# ============================================================================


def compute_surface_gravity():
    ratio = B_E / E_LIN
    arctan_val = math.atan2(E_LIN, B_E)
    m_param = OMEGA_E**2 * A_E**2 * B_E / GM_E
    aux_num = E_PRIME * (3 * (1 + ratio**2) * (1 - ratio * arctan_val) - 1)
    denom_common = (1 + 3 * ratio**2) * arctan_val - 3 * ratio
    gamma_a = GM_E * (1 - m_param - m_param * aux_num / (3 * denom_common)) / (A_E * B_E)
    gamma_b = GM_E * (1 + m_param * aux_num / (1.5 * denom_common)) / A_E**2
    return gamma_a, gamma_b


GAMMA_A, GAMMA_B = compute_surface_gravity()


def somigliana_mGal(lat_deg):
    lat_rad = math.radians(lat_deg)
    cos2 = math.cos(lat_rad)**2
    sin2 = math.sin(lat_rad)**2
    g0 = (A_E * GAMMA_A * cos2 + B_E * GAMMA_B * sin2) / math.sqrt(
        A_E**2 * cos2 + B_E**2 * sin2)
    return g0 * 1e5


def normal_gravity_mGal(lat_deg, height_m):
    return somigliana_mGal(lat_deg) - 0.3086 * height_m


# ============================================================================
# Prism gravity forward model (Nagy 2000 / Fukushima 2020)
# ============================================================================


def safe_atan2(y, x):
    if x == 0:
        if y > 0:
            return math.pi / 2
        elif y < 0:
            return -math.pi / 2
        else:
            return 0.0
    return math.atan(y / x)


def safe_log(x, y, z, r):
    if r == 0:
        return 0.0
    if x < 0:
        if y == 0.0 and z == 0.0:
            return -math.log(-2 * x)
        else:
            return math.log((y**2 + z**2) / (r - x))
    return math.log(x + r)


def kernel_u(e, n, u, r):
    return -(
        e * safe_log(n, u, e, r)
        + n * safe_log(e, n, u, r)
        - u * safe_atan2(e * n, u * r)
    )


def kernel_ee(e, n, u, r):
    if r == 0.0:
        return float("nan")
    return -safe_atan2(n * u, e * r)


def kernel_nn(e, n, u, r):
    if r == 0.0:
        return float("nan")
    return -safe_atan2(e * u, n * r)


def kernel_uu(e, n, u, r):
    if r == 0.0:
        return float("nan")
    return -safe_atan2(e * n, u * r)


def evaluate_kernel(easting, northing, upward, pw, pe, ps, pn, pb, pt, kernel):
    result = 0.0
    bounds_e = [pe, pw]
    bounds_n = [pn, ps]
    bounds_u = [pt, pb]
    for i in range(2):
        se = bounds_e[i] - easting
        for j in range(2):
            sn = bounds_n[j] - northing
            for k in range(2):
                su = bounds_u[k] - upward
                r = math.sqrt(se**2 + sn**2 + su**2)
                result += (-1) ** (i + j + k) * kernel(se, sn, su, r)
    return result


def gravity_u(ex, ny, uz, pw, pe, ps, pn, pb, pt, density):
    return G * density * evaluate_kernel(ex, ny, uz, pw, pe, ps, pn, pb, pt, kernel_u)


def gravity_ee(ex, ny, uz, pw, pe, ps, pn, pb, pt, density):
    return G * density * evaluate_kernel(ex, ny, uz, pw, pe, ps, pn, pb, pt, kernel_ee)


def gravity_nn(ex, ny, uz, pw, pe, ps, pn, pb, pt, density):
    return G * density * evaluate_kernel(ex, ny, uz, pw, pe, ps, pn, pb, pt, kernel_nn)


def gravity_uu(ex, ny, uz, pw, pe, ps, pn, pb, pt, density):
    return G * density * evaluate_kernel(ex, ny, uz, pw, pe, ps, pn, pb, pt, kernel_uu)


# ============================================================================
# Main solution
# ============================================================================


def main():
    # ---- Read input data ----
    survey = []
    with open("/app/survey.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            survey.append({
                "id": int(row["station_id"]),
                "lon": float(row["longitude"]),
                "lat": float(row["latitude"]),
                "height": float(row["height"]),
                "obs_gravity": float(row["observed_gravity"]),
            })

    with open("/app/prisms.json") as f:
        prisms_raw = json.load(f)
    prisms = [(p["west"], p["east"], p["south"], p["north"], p["bottom"], p["top"])
              for p in prisms_raw]

    with open("/app/proj_string.txt") as f:
        proj_string = f.read().strip()

    with open("/app/eval_points.json") as f:
        eval_points = json.load(f)

    n_stations = len(survey)
    n_prisms = len(prisms)

    # ---- Step 1: Project coordinates using PROJ CLI ----
    print("Projecting coordinates with PROJ...")
    input_lines = "\n".join(
        f"{s['lon']:.12f} {s['lat']:.12f}" for s in survey
    ) + "\n"

    result = subprocess.run(
        ["proj", "-f", "%.6f"] + proj_string.split(),
        input=input_lines, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"proj error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    projected = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        projected.append({"easting": float(parts[0]), "northing": float(parts[1])})

    with open("/app/projected_coords.json", "w") as f:
        json.dump(projected, f, indent=2)
    print(f"  Projected {len(projected)} stations.")

    # ---- Step 2: Compute normal gravity ----
    print("Computing normal gravity (Somigliana + free-air)...")
    ng_values = []
    for s in survey:
        ng = normal_gravity_mGal(s["lat"], s["height"])
        ng_values.append(ng)

    with open("/app/normal_gravity.json", "w") as f:
        json.dump(ng_values, f, indent=2)
    print(f"  Normal gravity range: {min(ng_values):.3f} - {max(ng_values):.3f} mGal")

    # ---- Step 3: Compute gravity disturbance and invert ----
    print("Building sensitivity matrix and inverting...")
    disturbance = [s["obs_gravity"] - ng for s, ng in zip(survey, ng_values)]

    # Build sensitivity matrix: G_mat[i, j] = g_u at station i from prism j with unit density (mGal)
    G_mat = np.zeros((n_stations, n_prisms))
    for s_idx in range(n_stations):
        ex = projected[s_idx]["easting"]
        ny = projected[s_idx]["northing"]
        uz = survey[s_idx]["height"]
        for p_idx, prism in enumerate(prisms):
            G_mat[s_idx, p_idx] = gravity_u(ex, ny, uz, *prism, 1.0) * 1e5

    obs_array = np.array(disturbance)
    densities, residuals, rank, sv = lstsq(G_mat, obs_array)

    with open("/app/densities.json", "w") as f:
        json.dump(densities.tolist(), f, indent=2)
    print(f"  Recovered densities: {densities.tolist()}")

    # ---- Step 4: GMT gridding ----
    print("Gridding disturbance with GMT surface...")
    xyz_path = "/app/anomaly.xyz"
    with open(xyz_path, "w") as f:
        for s_idx in range(n_stations):
            ex = projected[s_idx]["easting"]
            ny = projected[s_idx]["northing"]
            f.write(f"{ex} {ny} {disturbance[s_idx]}\n")

    result = subprocess.run(
        ["gmt", "surface", xyz_path,
         "-R-3000/3000/-3000/3000", "-I125", "-T0.25",
         "-G/app/anomaly_grid.nc"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"gmt surface error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("  Grid created: /app/anomaly_grid.nc")

    # ---- Step 5: Compute horizontal gradient with GMT grdmath ----
    print("Computing horizontal gradient magnitude...")
    result = subprocess.run(
        ["gmt", "grdmath",
         "/app/anomaly_grid.nc", "DDX", "2", "POW",
         "/app/anomaly_grid.nc", "DDY", "2", "POW",
         "ADD", "SQRT", "=", "/app/gradient.nc"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"gmt grdmath error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Extract maximum gradient
    result = subprocess.run(
        ["gmt", "grd2xyz", "/app/gradient.nc"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"gmt grd2xyz error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    max_grad = {"easting": 0, "northing": 0, "magnitude": 0}
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 3:
            try:
                mag = float(parts[2])
                if not math.isnan(mag) and mag > max_grad["magnitude"]:
                    max_grad = {
                        "easting": float(parts[0]),
                        "northing": float(parts[1]),
                        "magnitude": mag,
                    }
            except ValueError:
                continue

    with open("/app/gradient_max.json", "w") as f:
        json.dump(max_grad, f, indent=2)
    print(f"  Max gradient: {max_grad}")

    # ---- Step 6: Laplace equation verification ----
    print("Computing Laplace check...")
    laplace_values = []
    for pt in eval_points:
        ex, ny, uz = pt[0], pt[1], pt[2]
        total_ee = 0.0
        total_nn = 0.0
        total_uu = 0.0
        for p_idx, prism in enumerate(prisms):
            d = densities[p_idx]
            total_ee += gravity_ee(ex, ny, uz, *prism, d)
            total_nn += gravity_nn(ex, ny, uz, *prism, d)
            total_uu += gravity_uu(ex, ny, uz, *prism, d)
        laplace_values.append(total_ee + total_nn + total_uu)

    with open("/app/laplace_check.json", "w") as f:
        json.dump(laplace_values, f, indent=2)
    print(f"  Laplace residuals: {laplace_values}")
    print("Done.")


if __name__ == "__main__":
    main()
