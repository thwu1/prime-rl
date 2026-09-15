"""
CFD Boundary Layer Validation and Grid Convergence Analysis Pipeline.

"""

import json
import math

from scipy.optimize import minimize_scalar


def parse_data_file(filepath):
    """Parse tab-separated data file with # comment headers.

    Returns:
        header_dict: dict of key-value pairs from header comments
        data: list of (y_over_H, U_over_Uinf) tuples
    """
    header = {}
    data = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                # Parse key: value pairs from comments
                content = line.lstrip("#").strip()
                if ":" in content and "Columns" not in content:
                    parts = content.split(":", 1)
                    key = parts[0].strip()
                    val_str = parts[1].strip()
                    # Try to extract numeric value (handle units and +/-)
                    val_parts = val_str.split()
                    if val_parts:
                        try:
                            header[key] = float(val_parts[0])
                        except ValueError:
                            header[key] = val_str
                continue
            # Data line
            parts = line.split()
            if len(parts) >= 2:
                try:
                    y_H = float(parts[0])
                    U_Uinf = float(parts[1])
                    data.append((y_H, U_Uinf))
                except ValueError:
                    continue
    return header, data


def parse_grid_convergence(filepath):
    """Parse grid convergence CSV file."""
    grids = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if line.startswith("grid_level"):
                continue  # header
            parts = line.split(",")
            if len(parts) >= 6:
                grids.append({
                    "level": int(parts[0]),
                    "nx": int(parts[1]),
                    "ny": int(parts[2]),
                    "Cd": float(parts[3]),
                    "Cf_crest": float(parts[4]),
                    "Cp_te": float(parts[5]),
                })
    return sorted(grids, key=lambda g: g["level"])


def compute_bl_integrals(data, H_hill, U_inf, U_e, delta):
    """Compute boundary layer integral parameters from velocity profile data.

    Integrates from y=0 (no-slip) to delta using trapezoidal rule.
    """
    # Convert to dimensional coordinates and normalize by edge velocity
    y_dim = [d[0] * H_hill for d in data]
    u_over_ue = [d[1] * U_inf / U_e for d in data]

    # Prepend wall condition: y=0, U=0
    y_full = [0.0] + y_dim
    u_full = [0.0] + u_over_ue

    delta_star = 0.0
    theta = 0.0

    for i in range(len(y_full) - 1):
        y1 = y_full[i]
        y2 = y_full[i + 1]

        if y1 >= delta:
            break

        # Clip y2 to delta
        if y2 > delta:
            frac = (delta - y1) / (y2 - y1)
            u2 = u_full[i] + frac * (u_full[i + 1] - u_full[i])
            y2 = delta
        else:
            u2 = u_full[i + 1]

        u1 = u_full[i]

        # Clip U/Ue at 1.0 (cannot exceed edge velocity within BL)
        u1 = min(u1, 1.0)
        u2 = min(u2, 1.0)

        dy = y2 - y1

        # Trapezoidal rule
        delta_star += 0.5 * ((1.0 - u1) + (1.0 - u2)) * dy
        theta += 0.5 * (u1 * (1.0 - u1) + u2 * (1.0 - u2)) * dy

    H_factor = delta_star / theta if theta > 0 else float("nan")

    return delta_star, theta, H_factor


def spalding_yplus(uplus, kappa, B):
    """Compute y+ from u+ using Spalding's law of the wall."""
    ku = kappa * uplus
    return uplus + math.exp(-kappa * B) * (
        math.exp(ku) - 1.0 - ku - ku**2 / 2.0 - ku**3 / 6.0
    )


def spalding_fit(data, H_hill, U_inf, nu, kappa, B, n_fit_points=40):
    """Fit Spalding's law to PIV data to determine u_tau.

    Uses the inner-layer portion of the velocity profile.
    """
    y_dim = [d[0] * H_hill for d in data[:n_fit_points]]
    U_dim = [d[1] * U_inf for d in data[:n_fit_points]]

    def error(u_tau):
        total = 0.0
        for y, U in zip(y_dim, U_dim):
            yp_data = y * u_tau / nu
            up_data = U / u_tau
            yp_spalding = spalding_yplus(up_data, kappa, B)
            total += (yp_data - yp_spalding) ** 2
        return total

    result = minimize_scalar(error, bounds=(0.1, 5.0), method="bounded")
    return result.x


def richardson_extrapolation(f1, f2, f3, r):
    """Perform Richardson extrapolation using three grid solutions.

    Args:
        f1: solution on finest grid
        f2: solution on medium grid
        f3: solution on coarsest grid
        r: refinement ratio (h_coarse/h_fine)

    Returns:
        dict with convergence analysis results
    """
    eps21 = f2 - f1
    eps32 = f3 - f2

    if abs(eps21) < 1e-15:
        return {"convergence_type": "converged"}

    ratio = eps32 / eps21

    if ratio <= 0:
        return {"convergence_type": "oscillatory"}

    # Monotonic convergence
    p = math.log(abs(ratio)) / math.log(r)
    f_ext = f1 + (f1 - f2) / (r**p - 1.0)
    e_a = abs((f2 - f1) / f1)
    Fs = 1.25
    gci_fine = Fs * e_a / (r**p - 1.0)

    return {
        "convergence_type": "monotonic",
        "observed_order": round(p, 6),
        "f_extrapolated": round(f_ext, 8),
        "GCI_fine": round(gci_fine, 8),
    }


def main():
    # Load reference conditions
    with open("/app/data/reference_conditions.json") as f:
        config = json.load(f)

    kappa = config["spalding_constants"]["kappa"]
    B = config["spalding_constants"]["B"]

    results = {}

    # ================================================================
    # Part 1: Boundary Layer Integral Parameters (from rake data)
    # ================================================================
    bl_results = {}

    for re_label, filename in [("re250k", "rake_re250k.dat"), ("re650k", "rake_re650k.dat")]:
        header, data = parse_data_file(f"/app/data/{filename}")
        bl_config = config["boundary_layer"][re_label]

        H_hill = bl_config["H_hill"]
        U_inf = bl_config["U_inf"]
        U_e = bl_config["U_e"]
        delta = bl_config["delta"]

        ds, th, H = compute_bl_integrals(data, H_hill, U_inf, U_e, delta)

        bl_results[re_label] = {
            "delta_star": round(ds, 7),
            "theta": round(th, 7),
            "H": round(H, 5),
        }

    results["boundary_layer"] = bl_results

    # ================================================================
    # Part 2: Skin Friction via Spalding's Law (from PIV data)
    # ================================================================
    sf_results = {}

    for re_label, filename, piv_config_key in [
        ("re250k", "piv_re250k.dat", "piv_re250k"),
        ("re650k", "piv_re650k.dat", "piv_re650k"),
    ]:
        header, data = parse_data_file(f"/app/data/{filename}")
        piv_config = config["boundary_layer"][piv_config_key]

        H_hill = piv_config["H_hill"]
        U_inf = piv_config["U_inf"]
        U_e = piv_config["U_e"]
        nu = piv_config["nu"]

        u_tau = spalding_fit(data, H_hill, U_inf, nu, kappa, B)
        Cf = 2.0 * (u_tau / U_e) ** 2

        sf_results[re_label] = {
            "u_tau": round(u_tau, 6),
            "Cf": round(Cf, 8),
        }

    results["skin_friction"] = sf_results

    # ================================================================
    # Part 3: Grid Convergence (Richardson Extrapolation + GCI)
    # ================================================================
    grids = parse_grid_convergence("/app/data/grid_convergence.csv")

    # Compute refinement ratio from grid dimensions (using finest 3 grids)
    g1, g2, g3 = grids[0], grids[1], grids[2]
    r = g1["nx"] / g2["nx"]  # refinement ratio h_coarse/h_fine ≈ 2.0

    gc_results = {}

    for qty in ["Cd", "Cf_crest", "Cp_te"]:
        f1 = g1[qty]
        f2 = g2[qty]
        f3 = g3[qty]

        gc_results[qty] = richardson_extrapolation(f1, f2, f3, r)

    results["grid_convergence"] = gc_results

    # ================================================================
    # Write output
    # ================================================================
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
