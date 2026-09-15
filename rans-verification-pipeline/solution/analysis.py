"""
RANS Turbulence Model Verification Analysis Pipeline

Analyzes NASA TMR flat plate verification data:
- Richardson extrapolation & GCI analysis
- Boundary layer integral quantities
- Spalart-Allmaras auxiliary functions
- Spalding law of the wall fitting
- PLOT2D grid parsing and quality metrics
"""

import json
import math
import os


def parse_tecplot_zones(filepath, ncols):
    """Parse Tecplot-format data files with zone headers.

    Returns dict mapping zone name to list of tuples.
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
                # Extract zone title
                parts = stripped.split('"')
                if len(parts) >= 2:
                    current_zone = parts[1]
                else:
                    t_idx = stripped.lower().find("t=")
                    if t_idx >= 0:
                        current_zone = stripped[t_idx + 2:].strip().strip('"')
                    else:
                        current_zone = f"zone_{len(zones)}"
                current_data = []
                continue
            # Data line
            vals = stripped.split()
            if len(vals) >= ncols:
                try:
                    row = tuple(float(v) for v in vals[:ncols])
                    current_data.append(row)
                except ValueError:
                    continue

    if current_zone is not None:
        zones[current_zone] = current_data

    return zones


def richardson_extrapolation(f1, f2, f3, r=2.0, fs=1.25):
    """
    Roache GCI method using three finest grid solutions.

    f1: finest grid, f2: medium grid, f3: coarsest grid
    r: constant refinement ratio
    fs: safety factor (1.25 for 3+ grids)

    Returns dict with apparent_order, extrapolated_value, relative_error_percent,
    gci_fine_percent, fine_grid_value.
    """
    eps_32 = f3 - f2
    eps_21 = f2 - f1

    if abs(eps_21) < 1e-30:
        return {
            "apparent_order": 0.0,
            "extrapolated_value": f1,
            "fine_grid_value": f1,
            "relative_error_percent": 0.0,
            "gci_fine_percent": 0.0,
        }

    ratio = abs(eps_32 / eps_21)
    p = math.log(ratio) / math.log(r)

    # Extrapolated value
    f_ext = (r**p * f1 - f2) / (r**p - 1)

    # Approximate relative error
    e_a21 = abs((f1 - f2) / f1) * 100.0  # percent

    # GCI
    gci_fine = fs * e_a21 / (r**p - 1)  # percent

    return {
        "apparent_order": round(p, 4),
        "extrapolated_value": f_ext,
        "fine_grid_value": f1,
        "relative_error_percent": round(e_a21, 4),
        "gci_fine_percent": round(gci_fine, 4),
    }


def compute_gci_analysis(data_dir):
    """Compute GCI analysis for skin friction and drag."""
    results = {}

    for quantity, filename in [("skin_friction", "cf_convergence.dat"),
                                ("drag", "drag_convergence.dat")]:
        filepath = os.path.join(data_dir, filename)
        zones = parse_tecplot_zones(filepath, 4)

        qty_results = {}
        for zone_name, data in zones.items():
            # Data: N, h^2, h, f_value
            # Sorted by N descending (finest first)
            data_sorted = sorted(data, key=lambda x: x[0], reverse=True)

            f1 = data_sorted[0][3]  # finest
            f2 = data_sorted[1][3]  # medium
            f3 = data_sorted[2][3]  # coarsest of the three finest

            code_name = zone_name.lower().replace(" ", "")
            if "cfl3d" in code_name:
                key = "cfl3d"
            elif "fun3d" in code_name:
                key = "fun3d"
            else:
                key = code_name

            qty_results[key] = richardson_extrapolation(f1, f2, f3, r=2.0, fs=1.25)

        results[quantity] = qty_results

    return results


def compute_boundary_layer(data_dir):
    """Compute boundary layer integral quantities from velocity profile."""
    filepath = os.path.join(data_dir, "flatplate_u.dat")
    zones = parse_tecplot_zones(filepath, 2)

    # Get the first (and only) zone
    zone_data = list(zones.values())[0]

    u = [d[0] for d in zone_data]
    y = [d[1] for d in zone_data]
    n = len(u)

    # Edge velocity (max u in outer half of profile)
    u_edge = max(u[n // 2:])

    # delta_99 via interpolation
    u_99 = 0.99 * u_edge
    delta_99 = y[-1]  # fallback
    for i in range(1, n):
        if u[i] >= u_99:
            frac = (u_99 - u[i - 1]) / (u[i] - u[i - 1])
            delta_99 = y[i - 1] + frac * (y[i] - y[i - 1])
            break

    # Integration limit: 5 * delta_99
    ilimit = n
    for i in range(n):
        if y[i] > 5 * delta_99:
            ilimit = i
            break

    # Trapezoidal integration
    delta_star = 0.0
    theta = 0.0
    for i in range(1, ilimit):
        dy = y[i] - y[i - 1]
        f_ds_i = 1.0 - u[i] / u_edge
        f_ds_im1 = 1.0 - u[i - 1] / u_edge
        f_th_i = (u[i] / u_edge) * (1.0 - u[i] / u_edge)
        f_th_im1 = (u[i - 1] / u_edge) * (1.0 - u[i - 1] / u_edge)
        delta_star += 0.5 * (f_ds_i + f_ds_im1) * dy
        theta += 0.5 * (f_th_i + f_th_im1) * dy

    H = delta_star / theta if theta > 0 else 0.0

    return {
        "u_edge": u_edge,
        "delta_99": delta_99,
        "displacement_thickness": delta_star,
        "momentum_thickness": theta,
        "shape_factor": H,
    }


def sa_auxiliary_functions():
    """Implement and evaluate Spalart-Allmaras auxiliary functions."""
    cv1 = 7.1
    cw2 = 0.3
    cw3 = 2.0
    kappa = 0.41
    cb1 = 0.1355
    cb2 = 0.622
    sigma = 2.0 / 3.0

    def fv1(chi):
        return chi**3 / (chi**3 + cv1**3)

    def fv2(chi):
        return 1.0 - chi / (1.0 + chi * fv1(chi))

    def fw(r):
        g = r + cw2 * (r**6 - r)
        if abs(g) < 1e-30:
            return 0.0
        return g * ((1 + cw3**6) / (g**6 + cw3**6)) ** (1.0 / 6.0)

    cw1 = cb1 / kappa**2 + (1 + cb2) / sigma

    return {
        "fv1_at_chi_1": fv1(1.0),
        "fv1_at_chi_10": fv1(10.0),
        "fv2_at_chi_1": fv2(1.0),
        "fv2_at_chi_10": fv2(10.0),
        "fw_at_r_0p5": fw(0.5),
        "fw_at_r_1": fw(1.0),
        "cw1": cw1,
    }


def analyze_eddy_viscosity(data_dir):
    """Parse eddy viscosity profile and find peak."""
    filepath = os.path.join(data_dir, "mut_0.97.dat")
    zones = parse_tecplot_zones(filepath, 3)
    zone_data = list(zones.values())[0]

    # Find peak mu_t
    peak_idx = max(range(len(zone_data)), key=lambda i: zone_data[i][2])
    peak_mut = zone_data[peak_idx][2]
    y_at_peak = zone_data[peak_idx][1]

    return {
        "peak_mut_over_mu_inf": peak_mut,
        "y_at_peak_mut": y_at_peak,
    }


def fit_spalding_law(data_dir):
    """Fit Spalding's law of the wall to u+/y+ data using nonlinear least squares."""
    from scipy.optimize import least_squares

    filepath = os.path.join(data_dir, "flatplate_u+y+.dat")
    zones = parse_tecplot_zones(filepath, 2)
    zone_data = list(zones.values())[0]

    # Columns: log10(y+), u+
    log_yplus_data = [d[0] for d in zone_data]
    uplus_data = [d[1] for d in zone_data]
    yplus_data = [10.0**ly for ly in log_yplus_data]

    # Restrict to inner layer (y+ < 1000) to exclude wake region where
    # Spalding's law is not valid. Includes viscous sublayer + buffer + log-law.
    mask = [i for i in range(len(yplus_data)) if yplus_data[i] < 1000.0]
    yp_fit = [yplus_data[i] for i in mask]
    up_fit = [uplus_data[i] for i in mask]

    def spalding_yplus(uplus, kappa, B):
        """Spalding's law: y+ = u+ + (1/E)[exp(kappa*u+) - 1 - kappa*u+ - (kappa*u+)^2/2 - (kappa*u+)^3/6]"""
        E = math.exp(kappa * B)
        ku = kappa * uplus
        return uplus + (1.0 / E) * (math.exp(ku) - 1.0 - ku - ku**2 / 2.0 - ku**3 / 6.0)

    def residuals(params):
        kappa, B = params
        res = []
        for i in range(len(up_fit)):
            try:
                yp_pred = spalding_yplus(up_fit[i], kappa, B)
            except OverflowError:
                res.append(10.0)
                continue
            if yp_pred > 0 and yp_fit[i] > 0:
                res.append(math.log10(yp_pred) - math.log10(yp_fit[i]))
            else:
                res.append(0.0)
        return res

    result = least_squares(residuals, x0=[0.41, 5.0], bounds=([0.35, 3.0], [0.48, 7.0]))
    kappa_fit, B_fit = result.x

    # Compute RMS deviation over the fitted region
    res = residuals([kappa_fit, B_fit])
    rms = math.sqrt(sum(r**2 for r in res) / len(res))

    return {
        "kappa": float(kappa_fit),
        "B": float(B_fit),
        "rms_log_deviation": rms,
    }


def parse_plot2d_grid(data_dir):
    """Parse a PLOT2D format structured grid file."""
    filepath = os.path.join(data_dir, "flatplate_35x25.p2dfmt")

    with open(filepath) as f:
        lines = f.readlines()

    ngrids = int(lines[0].strip())
    dims = lines[1].split()
    nx = int(dims[0])
    ny = int(dims[1])

    # Parse all coordinate values
    coords = []
    for line in lines[2:]:
        for val in line.split():
            coords.append(float(val))

    total = nx * ny
    x_coords = coords[:total]
    y_coords = coords[total:2 * total]

    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)

    # Grid is stored in i-fastest ordering: index = j*nx + i
    # Find first on-plate grid point (x >= 0)
    first_plate_i = None
    for i in range(nx):
        if x_coords[i] >= 0:
            first_plate_i = i
            break

    # First cell height at the first on-plate point
    if first_plate_i is not None:
        y_wall = y_coords[0 * nx + first_plate_i]
        y_next = y_coords[1 * nx + first_plate_i]
        first_cell_height = abs(y_next - y_wall)
    else:
        first_cell_height = 0.0

    # Maximum wall-normal stretching ratio on the plate
    max_stretch = 1.0
    for i in range(nx):
        if x_coords[i] < 0:
            continue
        for j in range(1, ny - 1):
            dy_prev = abs(y_coords[j * nx + i] - y_coords[(j - 1) * nx + i])
            dy_next = abs(y_coords[(j + 1) * nx + i] - y_coords[j * nx + i])
            if dy_prev > 1e-30:
                ratio = dy_next / dy_prev
                if ratio > max_stretch:
                    max_stretch = ratio

    return {
        "nx": nx,
        "ny": ny,
        "x_range": [x_min, x_max],
        "y_range": [y_min, y_max],
        "first_cell_height": first_cell_height,
        "max_wall_normal_stretching_ratio": max_stretch,
    }


def main():
    data_dir = "/data"

    # 1. GCI Analysis
    gci = compute_gci_analysis(data_dir)

    # 2. Boundary Layer Analysis
    bl = compute_boundary_layer(data_dir)

    # 3. SA Model Auxiliary Functions + Eddy Viscosity Profile
    sa = sa_auxiliary_functions()
    ev = analyze_eddy_viscosity(data_dir)
    sa.update(ev)

    # 4. Law of the Wall Fitting
    low = fit_spalding_law(data_dir)

    # 5. Grid Metrics
    grid = parse_plot2d_grid(data_dir)

    results = {
        "gci_analysis": gci,
        "boundary_layer": bl,
        "sa_model": sa,
        "law_of_wall": low,
        "grid_metrics": grid,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
