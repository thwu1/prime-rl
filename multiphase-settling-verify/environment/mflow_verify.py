"""
MFiX-lite: Multiphase Flow Verification Framework
Implements particle drag, settling, and MMS verification analyses.
"""

import json
import math
import sys

try:
    import tomllib
except ImportError:
    import tomli as tomllib


def load_config(path="/app/config.toml"):
    with open(path, "rb") as f:
        return tomllib.load(f)


# =====================================================================
# Drag Correlation
# =====================================================================

def schiller_naumann_cd(Re):
    """Single-particle drag coefficient: Schiller-Naumann correlation."""
    if Re > 1000.0:
        return 0.44
    return (24.0 / Re) * (1.0 + 0.15 * Re ** 0.678)


def compute_drag(config):
    """Evaluate drag coefficients at specified Reynolds numbers."""
    re_values = config["drag"]["reynolds_numbers"]
    results = {}
    for Re in re_values:
        results[f"Re_{Re}"] = schiller_naumann_cd(Re)
    return results


# =====================================================================
# Particle Settling - Kinematic Shock Analysis
# =====================================================================

def compute_settling(config):
    """Batch particle settling with Richardson-Zaki hindered settling."""
    phys = config["physical"]
    g = phys["gravity"]
    rho_g = phys["fluid_density"]
    rho_s = phys["solid_density"]
    mu = phys["fluid_viscosity"]
    d_p = phys["particle_diameter"]
    n = phys["richardson_zaki_n"]
    eps_max = phys["max_packing"]
    y0 = phys["initial_bed_top"]
    t = phys["eval_time"]

    # Stokes terminal velocity
    u_t = g * (rho_s - rho_g) * d_p ** 2 / (18.0 * mu)
    Re_t = rho_g * u_t * d_p / mu

    fronts = []
    for eps_s0 in phys["concentrations"]:
        eps_g0 = 1.0 - eps_s0

        # Richardson-Zaki hindered settling velocity
        u_r = u_t * eps_g0 ** n

        # Shock wave velocities from Rankine-Hugoniot conditions
        # Settling front: suspension/clear-fluid interface
        sigma_settle = -u_t * eps_g0 ** n
        x_settle = y0 + sigma_settle * t

        # Filling front: suspension/packed-bed interface
        sigma_fill = u_t * eps_s0 * eps_g0 ** n / (eps_max - eps_s0)
        x_fill = sigma_fill * t

        fronts.append({
            "eps_s0": eps_s0,
            "settling_front": x_settle,
            "filling_front": x_fill,
            "hindered_velocity": u_r,
        })

    return {
        "terminal_velocity": u_t,
        "reynolds_number": Re_t,
        "fronts": fronts,
    }


# =====================================================================
# Method of Manufactured Solutions (MMS) Verification
# =====================================================================

def compute_mms(config):
    """
    MMS verification for 1D steady diffusion: -alpha * u'' = S(x).
    Manufactured solution: u(x) = A + B * sin(k * pi * x / L)
    """
    mms = config["mms"]
    alpha = mms["diffusivity"]
    A = mms["amplitude_A"]
    B = mms["amplitude_B"]
    k = mms["wavenumber"]
    L = mms["domain_length"]
    grid_levels = mms["grid_levels"]

    kpi_L = k * math.pi / L

    l2_norms = {}
    for N in grid_levels:
        h = L / N
        n_int = N - 1
        x = [(i + 1) * h for i in range(n_int)]

        # Exact manufactured solution
        u_exact = [A + B * math.sin(kpi_L * xi) for xi in x]

        # Source term: S(x) derived from the manufactured solution
        # u''(x) = -B * (kpi/L)^2 * sin(kpi*x/L)
        # For equation -alpha * u'' = S(x), the source is:
        source = [-alpha * B * kpi_L ** 2 * math.sin(kpi_L * xi) for xi in x]

        # Dirichlet boundary conditions from exact solution
        u_left = A + B * math.sin(0.0)
        u_right = A + B * math.sin(kpi_L * L)

        # Second-order central finite differences
        coeff = alpha / h ** 2
        a_diag = [-coeff] * n_int
        b_diag = [2.0 * coeff] * n_int
        c_diag = [-coeff] * n_int
        d_vec = list(source)

        d_vec[0] += coeff * u_left
        d_vec[-1] += coeff * u_right

        # Thomas algorithm
        for i in range(1, n_int):
            w = a_diag[i] / b_diag[i - 1]
            b_diag[i] -= w * c_diag[i - 1]
            d_vec[i] -= w * d_vec[i - 1]

        u_num = [0.0] * n_int
        u_num[-1] = d_vec[-1] / b_diag[-1]
        for i in range(n_int - 2, -1, -1):
            u_num[i] = (d_vec[i] - c_diag[i] * u_num[i + 1]) / b_diag[i]

        # L2 error norm (RMS)
        err_sq = sum((u_num[i] - u_exact[i]) ** 2 for i in range(n_int))
        l2 = math.sqrt(err_sq / n_int)
        l2_norms[str(N)] = l2

    # Observed convergence orders
    observed_orders = {}
    sorted_levels = sorted(grid_levels)
    for i in range(len(sorted_levels) - 1):
        N1, N2 = sorted_levels[i], sorted_levels[i + 1]
        r = N2 / N1
        e1, e2 = l2_norms[str(N1)], l2_norms[str(N2)]
        if e1 > 0 and e2 > 0:
            p = math.log(e1 / e2) / math.log(r)
            observed_orders[f"{N1}_to_{N2}"] = round(p, 6)

    return {"l2_norms": l2_norms, "observed_orders": observed_orders}


# =====================================================================
# Main
# =====================================================================

def main():
    config = load_config()

    results = {
        "drag": compute_drag(config),
        "settling": compute_settling(config),
        "mms": compute_mms(config),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Verification results written to /app/results.json")

    print("\n--- Drag Coefficients ---")
    for key, val in results["drag"].items():
        print(f"  {key}: {val:.6f}")

    print("\n--- Settling Analysis ---")
    print(f"  Terminal velocity: {results['settling']['terminal_velocity']:.6e} m/s")
    print(f"  Particle Re: {results['settling']['reynolds_number']:.4f}")
    for fr in results["settling"]["fronts"]:
        print(f"  eps_s0={fr['eps_s0']:.2f}: settle={fr['settling_front']:.6f} m, "
              f"fill={fr['filling_front']:.6f} m")

    print("\n--- MMS Grid Convergence ---")
    for key, val in results["mms"]["l2_norms"].items():
        print(f"  N={key}: L2 = {val:.6e}")
    print("  Observed orders:")
    for key, val in results["mms"]["observed_orders"].items():
        print(f"    {key}: p = {val:.4f}")


if __name__ == "__main__":
    main()
