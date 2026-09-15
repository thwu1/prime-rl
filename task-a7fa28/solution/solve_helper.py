#!/usr/bin/env python3

"""
CFD verification audit solution.
Parses NASA TMR data and performs:
1. Grid convergence discretization uncertainty (ASME GCI procedure)
2. Convergence quality assessment
3. PLOT3D grid quality metrics
4. Boundary layer integral properties
5. Spalart-Allmaras eddy viscosity inversion
"""

import json
import math
import re


def parse_tecplot(filepath):
    """Parse a multi-zone Tecplot ASCII file.

    Returns (variables, zones) where zones is a dict mapping
    zone name to list of data rows (each row is a list of floats).
    """
    variables = []
    zones = {}
    current_zone = None

    with open(filepath) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            low = line.lower()
            if low.startswith("variables"):
                var_part = line.split("=", 1)[1]
                variables = [
                    v.strip().strip('"').strip("'") for v in var_part.split(",")
                ]
                continue

            if low.startswith("zone"):
                match = re.search(r't\s*=\s*"([^"]*)"', line, re.IGNORECASE)
                if not match:
                    match = re.search(r"t\s*=\s*'([^']*)'", line, re.IGNORECASE)
                if match:
                    current_zone = match.group(1).strip()
                else:
                    current_zone = f"zone_{len(zones)}"
                zones[current_zone] = []
                continue

            tokens = line.split()
            try:
                row = [float(t) for t in tokens]
                if current_zone is not None:
                    zones[current_zone].append(row)
            except ValueError:
                pass

    return variables, zones


def parse_plot3d_2d(filepath):
    """Parse a PLOT3D 2D structured grid file (ASCII, single-block).

    Returns (ni, nj, x_2d, y_2d) where x_2d[j][i] and y_2d[j][i].
    """
    with open(filepath) as f:
        lines = f.readlines()

    nblocks = int(lines[0].strip())
    dims = lines[1].strip().split()
    ni, nj = int(dims[0]), int(dims[1])

    values = []
    for line in lines[2:]:
        for token in line.split():
            values.append(float(token))

    npts = ni * nj
    x_flat = values[0:npts]
    y_flat = values[npts:2 * npts]

    # Reshape: i varies fastest (Fortran ordering)
    x_2d = []
    y_2d = []
    for j in range(nj):
        x_2d.append(x_flat[j * ni:(j + 1) * ni])
        y_2d.append(y_flat[j * ni:(j + 1) * ni])

    return ni, nj, x_2d, y_2d


# ============================================================
# Analysis 1: Grid Convergence Index (ASME procedure)
# ============================================================

def compute_gci(f1, f2, f3, r21=2.0):
    """Compute GCI metrics using finest three grid solutions.

    f1 = finest grid, f2 = medium, f3 = coarsest.
    r21 = refinement ratio h2/h1 (uniform, = r32).
    """
    eps21 = f2 - f1
    eps32 = f3 - f2

    ratio = abs(eps32 / eps21)
    p = abs(math.log(ratio)) / math.log(r21)

    r21p = r21 ** p
    f_ext = (r21p * f1 - f2) / (r21p - 1)

    ea21 = abs((f1 - f2) / f1) * 100.0
    eext21 = abs((f_ext - f1) / f_ext) * 100.0
    ea21_frac = abs((f1 - f2) / f1)
    gci_fine = 1.25 * ea21_frac / (r21p - 1) * 100.0

    return {
        "p": round(p, 4),
        "ea21_pct": round(ea21, 4),
        "eext21_pct": round(eext21, 4),
        "gci_fine_pct": round(gci_fine, 4),
        "f_extrapolated": f_ext,
    }


def run_gci_analysis():
    """Run GCI analysis on skin friction and drag convergence data."""
    result = {}

    for metric, filename in [
        ("skin_friction", "/app/data/cf_convergence.dat"),
        ("drag", "/app/data/drag_convergence.dat"),
    ]:
        _, zones = parse_tecplot(filename)
        metric_result = {}

        for code_name, zone_data in zones.items():
            sorted_data = sorted(zone_data, key=lambda r: r[0], reverse=True)
            f1 = sorted_data[0][3]
            f2 = sorted_data[1][3]
            f3 = sorted_data[2][3]
            metric_result[code_name] = compute_gci(f1, f2, f3, r21=2.0)

        result[metric] = metric_result

    return result


# ============================================================
# Analysis 2: Convergence Quality Assessment
# ============================================================

def run_convergence_assessment():
    """Assess convergence behavior for each code/metric combination."""
    result = {}

    for metric, filename in [
        ("skin_friction", "/app/data/cf_convergence.dat"),
        ("drag", "/app/data/drag_convergence.dat"),
    ]:
        _, zones = parse_tecplot(filename)
        metric_result = {}

        for code_name, zone_data in zones.items():
            # Sort by N descending (finest first)
            sorted_data = sorted(zone_data, key=lambda r: r[0], reverse=True)
            fvals = [row[3] for row in sorted_data]

            # Monotonicity: check if all successive differences have the
            # same sign across all five grid levels
            diffs = [fvals[i + 1] - fvals[i] for i in range(len(fvals) - 1)]
            all_positive = all(d > 0 for d in diffs)
            all_negative = all(d < 0 for d in diffs)
            monotonic = all_positive or all_negative

            # Asymptotic range: compute apparent order from finest three
            # grids and check if close to formal order (2 for 2nd-order)
            f1, f2, f3 = fvals[0], fvals[1], fvals[2]
            eps21 = f2 - f1
            eps32 = f3 - f2
            ratio = abs(eps32 / eps21)
            p = abs(math.log(ratio)) / math.log(2.0)

            # In asymptotic range if p is within ~25% of design order (2)
            in_asymptotic = p > 1.5

            metric_result[code_name] = {
                "monotonic": monotonic,
                "in_asymptotic_range": in_asymptotic,
            }

        result[metric] = metric_result

    return result


# ============================================================
# Analysis 3: PLOT3D Grid Quality Metrics
# ============================================================

def run_grid_quality_analysis():
    """Parse PLOT3D grid and compute quality metrics."""
    ni, nj, x2d, y2d = parse_plot3d_2d("/app/data/flatplate_grid.p2d")

    # Count plate points (x in [0, 2] at the wall j=0)
    plate_indices = [
        i for i in range(ni) if x2d[0][i] >= 0.0 and x2d[0][i] <= 2.0
    ]
    plate_points = len(plate_indices)

    # Minimum wall spacing on plate (dy from j=0 to j=1)
    wall_spacings = [y2d[1][i] - y2d[0][i] for i in plate_indices]
    min_wall_spacing = min(wall_spacings)

    # Maximum stretching ratio in wall-normal direction
    # Use a representative plate point
    i_mid = plate_indices[len(plate_indices) // 2]
    dy_vals = [y2d[j + 1][i_mid] - y2d[j][i_mid] for j in range(nj - 1)]
    stretch_ratios = [
        dy_vals[j + 1] / dy_vals[j]
        for j in range(len(dy_vals) - 1)
        if dy_vals[j] > 1e-15
    ]
    max_stretching = max(stretch_ratios) if stretch_ratios else 0.0

    return {
        "dimensions": [ni, nj],
        "min_wall_spacing": min_wall_spacing,
        "max_stretching_ratio": round(max_stretching, 6),
        "plate_points": plate_points,
    }


# ============================================================
# Analysis 4: Boundary Layer Integral Properties
# ============================================================

def run_boundary_layer_analysis():
    """Compute BL properties from velocity profile at x=0.97008."""
    _, zones = parse_tecplot("/app/data/flatplate_u.dat")

    target_zone = None
    for name in zones:
        if "0.97" in name:
            target_zone = name
            break

    if target_zone is None:
        raise ValueError("Could not find velocity profile zone at x=0.97")

    data = zones[target_zone]
    profile = [(row[0], row[1]) for row in data]
    U_e = profile[-1][0]

    # delta_99: interpolate where u/U_e = 0.99
    target_u = 0.99 * U_e
    delta_99 = None
    for i in range(1, len(profile)):
        u_curr, y_curr = profile[i]
        u_prev, y_prev = profile[i - 1]
        if u_curr >= target_u and u_prev < target_u:
            frac = (target_u - u_prev) / (u_curr - u_prev)
            delta_99 = y_prev + frac * (y_curr - y_prev)
            break

    if delta_99 is None:
        for u, y in profile:
            if u >= target_u:
                delta_99 = y
                break

    # Displacement thickness
    delta_star = 0.0
    for i in range(1, len(profile)):
        u1, y1 = profile[i - 1]
        u2, y2 = profile[i]
        dy = y2 - y1
        f1 = 1.0 - u1 / U_e
        f2 = 1.0 - u2 / U_e
        delta_star += 0.5 * (f1 + f2) * dy

    # Momentum thickness
    theta = 0.0
    for i in range(1, len(profile)):
        u1, y1 = profile[i - 1]
        u2, y2 = profile[i]
        dy = y2 - y1
        g1 = (u1 / U_e) * (1.0 - u1 / U_e)
        g2 = (u2 / U_e) * (1.0 - u2 / U_e)
        theta += 0.5 * (g1 + g2) * dy

    shape_factor = delta_star / theta

    return {
        "delta_99": delta_99,
        "delta_star": delta_star,
        "theta": theta,
        "shape_factor": round(shape_factor, 6),
    }


# ============================================================
# Analysis 5: SA Model Eddy Viscosity Inversion
# ============================================================

def chi_times_fv1(chi, cv1_cubed=7.1 ** 3):
    """Compute chi * fv1(chi) = chi^4 / (chi^3 + cv1^3)."""
    return chi ** 4 / (chi ** 3 + cv1_cubed)


def invert_fv1(R, cv1=7.1, tol=1e-12, max_iter=200):
    """Solve chi * fv1(chi) = R for chi via bisection."""
    cv1_cubed = cv1 ** 3

    if R < 1e-15:
        return 0.0

    lo = 0.0
    hi = max(R + cv1 + 10, 2 * R)

    while chi_times_fv1(hi, cv1_cubed) < R:
        hi *= 2

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        val = chi_times_fv1(mid, cv1_cubed)
        if abs(val - R) < tol * max(1.0, R):
            return mid
        if val < R:
            lo = mid
        else:
            hi = mid

    return 0.5 * (lo + hi)


def run_sa_verification():
    """Invert SA fv1 to recover chi from eddy viscosity profile."""
    _, zones = parse_tecplot("/app/data/mut_profile.dat")

    zone_name = list(zones.keys())[0]
    data = zones[zone_name]

    max_idx = max(range(len(data)), key=lambda i: data[i][2])
    _, peak_y, peak_mut = data[max_idx]

    peak_chi = invert_fv1(peak_mut)

    _, _, fs_mut = data[-1]
    freestream_chi = invert_fv1(fs_mut)

    return {
        "peak_chi": round(peak_chi, 4),
        "peak_y": peak_y,
        "freestream_chi": round(freestream_chi, 4),
        "peak_mut_over_mu": peak_mut,
    }


# ============================================================
# Main
# ============================================================

def main():
    results = {
        "gci": run_gci_analysis(),
        "convergence_assessment": run_convergence_assessment(),
        "grid_quality": run_grid_quality_analysis(),
        "boundary_layer": run_boundary_layer_analysis(),
        "sa_verification": run_sa_verification(),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Verification audit complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
