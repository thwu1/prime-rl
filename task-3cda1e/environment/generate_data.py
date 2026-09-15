#!/usr/bin/env python3
"""Generate input data files for the geodetic gravity survey task.
Runs at Docker build time; deleted before final image."""
import json
import math
import csv
import subprocess
import sys
import os

# ============================================================================
# Constants
# ============================================================================
G = 6.6743e-11

# GRS80 ellipsoid parameters
A_E = 6378137.0
F_E = 1.0 / 298.257222101
B_E = A_E * (1 - F_E)
GM_E = 3986005.0e8
OMEGA_E = 7292115e-11

E2 = 2 * F_E - F_E**2
E_LIN = math.sqrt(A_E**2 - B_E**2)
E_PRIME = E_LIN / B_E

PROJ_STRING = "+proj=tmerc +lat_0=45.0 +lon_0=-75.0 +k_0=1.0 +x_0=0 +y_0=0 +ellps=GRS80 +units=m +no_defs"

TRUE_DENSITIES = [300.0, -200.0, 500.0, 150.0, -350.0]

PRISMS = [
    {"west": -500, "east": 500, "south": -500, "north": 500, "bottom": -2000, "top": -1000},
    {"west": 1000, "east": 2000, "south": -300, "north": 300, "bottom": -1500, "top": -500},
    {"west": -2000, "east": -1000, "south": 500, "north": 1500, "bottom": -3000, "top": -2000},
    {"west": -300, "east": 300, "south": -2000, "north": -1000, "bottom": -800, "top": -200},
    {"west": 500, "east": 1500, "south": 1000, "north": 2000, "bottom": -1200, "top": -400},
]

XS = [-2500.0, -1500.0, -500.0, 500.0, 1500.0, 2500.0]
YS = [-2500.0, -1500.0, -500.0, 500.0, 1500.0, 2500.0]

EVAL_POINTS = [
    [0.0, 0.0, 1000.0],
    [1200.0, 800.0, 500.0],
    [-1500.0, -1500.0, 200.0],
    [3000.0, 0.0, 100.0],
    [-500.0, 2500.0, 300.0],
    [2000.0, -2000.0, 400.0],
    [0.0, 3000.0, 150.0],
    [-3000.0, 1000.0, 600.0],
]

# ============================================================================
# Normal gravity (Somigliana)
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

# ============================================================================
# Prism gravity forward model
# ============================================================================

def safe_atan2(y, x):
    if x == 0:
        if y > 0: return math.pi / 2
        elif y < 0: return -math.pi / 2
        else: return 0.0
    return math.atan(y / x)

def safe_log(x, y, z, r):
    if r == 0: return 0.0
    if x < 0:
        if y == 0.0 and z == 0.0:
            return -math.log(-2 * x)
        else:
            return math.log((y**2 + z**2) / (r - x))
    return math.log(x + r)

def kernel_u(e, n, u, r):
    return -(e * safe_log(n, u, e, r) + n * safe_log(e, n, u, r) - u * safe_atan2(e * n, u * r))

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
                result += (-1)**(i + j + k) * kernel(se, sn, su, r)
    return result

def gravity_u_mGal(x, y, z, pw, pe, ps, pn, pb, pt, density):
    return G * density * evaluate_kernel(x, y, z, pw, pe, ps, pn, pb, pt, kernel_u) * 1e5

# ============================================================================
# Main
# ============================================================================

def main():
    os.makedirs("/app", exist_ok=True)

    # Build batch input for proj inverse: local (x, y) -> geographic (lon, lat)
    positions = []
    lines = []
    for iy in range(6):
        for ix in range(6):
            x, y = XS[ix], YS[iy]
            positions.append((x, y))
            lines.append(f"{x} {y}")
    input_str = "\n".join(lines) + "\n"

    result = subprocess.run(
        ["proj", "-I", "-f", "%.12f"] + PROJ_STRING.split(),
        input=input_str, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"proj error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    output_lines = result.stdout.strip().split("\n")

    # Build survey data
    stations = []
    for i, line in enumerate(output_lines):
        parts = line.split()
        lon, lat = float(parts[0]), float(parts[1])
        x, y = positions[i]

        ng = somigliana_mGal(lat)

        anomaly = 0.0
        for pi, prism in enumerate(PRISMS):
            anomaly += gravity_u_mGal(
                x, y, 0.0,
                prism["west"], prism["east"],
                prism["south"], prism["north"],
                prism["bottom"], prism["top"],
                TRUE_DENSITIES[pi]
            )

        obs_gravity = ng + anomaly
        stations.append({
            "id": i, "lon": lon, "lat": lat,
            "obs_gravity": obs_gravity
        })

    # Write survey.csv
    with open("/app/survey.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["station_id", "longitude", "latitude", "height", "observed_gravity"])
        for s in stations:
            writer.writerow([s["id"], f"{s['lon']:.12f}", f"{s['lat']:.12f}",
                           "0.0", f"{s['obs_gravity']:.12f}"])

    # Write prisms.json
    with open("/app/prisms.json", "w") as f:
        json.dump(PRISMS, f, indent=2)

    # Write proj_string.txt
    with open("/app/proj_string.txt", "w") as f:
        f.write(PROJ_STRING + "\n")

    # Write eval_points.json
    with open("/app/eval_points.json", "w") as f:
        json.dump(EVAL_POINTS, f, indent=2)

    print("Data generation complete.")
    print(f"  gamma_a = {GAMMA_A:.12e} m/s^2")
    print(f"  gamma_b = {GAMMA_B:.12e} m/s^2")
    print(f"  Stations: {len(stations)}")

if __name__ == "__main__":
    main()
