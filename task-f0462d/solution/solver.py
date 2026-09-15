#!/usr/bin/env python3
"""
Solve the rectangular prism gravity inversion problem.

"""
import json
import math
import subprocess

import numpy as np

G = 6.674e-11  # gravitational constant, m^3/(kg*s^2)


# ---------------------------------------------------------------------------
# Numerically safe helper functions
# ---------------------------------------------------------------------------

def safe_log(x, y, z, r):
    """
    Compute ln(x + r) in a numerically stable way.

    Three branches:
      - r = 0  -> return 0 (vertex singularity, multiplied by zero in kernel)
      - x < 0  -> use identity ln(x+r) = ln((y^2+z^2)/(r-x)) to avoid
                   catastrophic cancellation; special sub-case y=z=0
      - x >= 0 -> direct formula ln(x + r)
    """
    if r == 0.0:
        return 0.0
    if x < 0.0:
        if y == 0.0 and z == 0.0:
            return -math.log(-2.0 * x)
        return math.log((y * y + z * z) / (r - x))
    return math.log(x + r)


def safe_atan2(y, x):
    """
    Principal-value arctan(y/x) with safe handling when x = 0.
    """
    if x != 0.0:
        return math.atan(y / x)
    if y > 0.0:
        return math.pi / 2.0
    if y < 0.0:
        return -math.pi / 2.0
    return 0.0


# ---------------------------------------------------------------------------
# Gravity kernels
# ---------------------------------------------------------------------------

def kernel_u(e, n, u):
    """Kernel for the upward component of gravitational acceleration."""
    r = math.sqrt(e * e + n * n + u * u)
    return (
        e * safe_log(n, e, u, r)
        + n * safe_log(e, n, u, r)
        - u * safe_atan2(e * n, u * r)
    )


def kernel_ee(e, n, u):
    """Second derivative of potential w.r.t. easting."""
    r = math.sqrt(e * e + n * n + u * u)
    if r == 0.0:
        return float("nan")
    return -safe_atan2(n * u, e * r)


def kernel_nn(e, n, u):
    """Second derivative of potential w.r.t. northing."""
    r = math.sqrt(e * e + n * n + u * u)
    if r == 0.0:
        return float("nan")
    return -safe_atan2(u * e, n * r)


def kernel_uu(e, n, u):
    """Second derivative of potential w.r.t. upward."""
    r = math.sqrt(e * e + n * n + u * u)
    if r == 0.0:
        return float("nan")
    return -safe_atan2(e * n, u * r)


# ---------------------------------------------------------------------------
# Forward model functions
# ---------------------------------------------------------------------------

def _evaluate_kernel(obs_e, obs_n, obs_up, prism, density, kfunc, sign_factor):
    """Evaluate a gravity kernel over the 8 prism vertices with alternating signs."""
    w, ep, s, np_, bot, top = prism
    shifts_e = [w - obs_e, ep - obs_e]
    shifts_n = [s - obs_n, np_ - obs_n]
    shifts_up = [bot - obs_up, top - obs_up]
    result = 0.0
    for i in range(2):
        for j in range(2):
            for k in range(2):
                sign = (-1) ** (i + j + k)
                result += sign * kfunc(shifts_e[i], shifts_n[j], shifts_up[k])
    return sign_factor * G * density * result


def gravity_u(obs_e, obs_n, obs_up, prism, density):
    """Vertical (upward) component of gravitational acceleration (m/s^2)."""
    return _evaluate_kernel(obs_e, obs_n, obs_up, prism, density, kernel_u, -1.0)


def gravity_ee(obs_e, obs_n, obs_up, prism, density):
    """Second derivative of potential w.r.t. easting (1/s^2)."""
    return _evaluate_kernel(obs_e, obs_n, obs_up, prism, density, kernel_ee, 1.0)


def gravity_nn(obs_e, obs_n, obs_up, prism, density):
    """Second derivative of potential w.r.t. northing (1/s^2)."""
    return _evaluate_kernel(obs_e, obs_n, obs_up, prism, density, kernel_nn, 1.0)


def gravity_uu(obs_e, obs_n, obs_up, prism, density):
    """Second derivative of potential w.r.t. upward (1/s^2)."""
    return _evaluate_kernel(obs_e, obs_n, obs_up, prism, density, kernel_uu, 1.0)


# ---------------------------------------------------------------------------
# Main: build Jacobian, invert, verify Laplace, diagnostics, visualization
# ---------------------------------------------------------------------------

def main():
    # Load input data
    with open("/app/problem_config.json") as f:
        config = json.load(f)
    with open("/app/observed_gravity.json") as f:
        obs_data = json.load(f)

    prisms = config["prisms"]
    observations = obs_data["observations"]
    laplace_points = config["laplace_test_points"]

    n_obs = len(observations)
    n_prisms = len(prisms)

    print(f"Building {n_obs} x {n_prisms} sensitivity matrix...")

    # Build sensitivity (Jacobian) matrix: G_mat[i,j] = g_u at obs[i] due to prism[j]
    # with unit density (1 kg/m^3)
    G_mat = np.zeros((n_obs, n_prisms))
    for i, obs in enumerate(observations):
        for j, prism in enumerate(prisms):
            G_mat[i, j] = gravity_u(
                obs["easting"], obs["northing"], obs["upward"], prism, 1.0
            )

    # Data vector
    d = np.array([obs["g_u"] for obs in observations])

    # Compute condition number via SVD
    sv = np.linalg.svd(G_mat, compute_uv=False)
    cond_number = float(sv[0] / sv[-1])
    print(f"  Condition number: {cond_number:.1f}")

    # Solve least-squares: min ||G_mat @ m - d||^2
    print("Solving least-squares inversion...")
    densities, residuals, rank, _ = np.linalg.lstsq(G_mat, d, rcond=None)

    print(f"  Rank: {rank}")
    print(f"  Density range: [{densities.min():.1f}, {densities.max():.1f}] kg/m^3")

    # Data fit
    predicted = G_mat @ densities
    data_residual = predicted - d
    data_rms = float(np.sqrt(np.mean(data_residual ** 2)))
    print(f"  Data RMS misfit: {data_rms:.6e} m/s^2")

    # Write recovered densities
    with open("/app/recovered_densities.json", "w") as f:
        json.dump({"densities": densities.tolist()}, f, indent=2)
    print("Wrote /app/recovered_densities.json")

    # Write inversion diagnostics
    diagnostics = {
        "condition_number": cond_number,
        "data_rms_misfit": data_rms,
        "n_observations": n_obs,
        "n_parameters": n_prisms,
    }
    with open("/app/inversion_diagnostics.json", "w") as f:
        json.dump(diagnostics, f, indent=2)
    print("Wrote /app/inversion_diagnostics.json")

    # Laplace equation verification
    print(f"Verifying Laplace's equation at {len(laplace_points)} test points...")
    laplace_results = []
    for point in laplace_points:
        e = point["easting"]
        n = point["northing"]
        u = point["upward"]
        g_ee_total = 0.0
        g_nn_total = 0.0
        g_uu_total = 0.0
        for p_idx, prism in enumerate(prisms):
            dens = densities[p_idx]
            if abs(dens) > 1e-10:
                g_ee_total += gravity_ee(e, n, u, prism, dens)
                g_nn_total += gravity_nn(e, n, u, prism, dens)
                g_uu_total += gravity_uu(e, n, u, prism, dens)
        laplace_res = g_ee_total + g_nn_total + g_uu_total
        laplace_results.append({
            "easting": e,
            "northing": n,
            "upward": u,
            "g_ee": g_ee_total,
            "g_nn": g_nn_total,
            "g_uu": g_uu_total,
            "laplace_residual": laplace_res,
        })

    with open("/app/laplace_verification.json", "w") as f:
        json.dump({"results": laplace_results}, f, indent=2)
    print("Wrote /app/laplace_verification.json")

    # Summary
    max_laplace = max(abs(r["laplace_residual"]) for r in laplace_results)
    max_comp = max(
        max(abs(r["g_ee"]), abs(r["g_nn"]), abs(r["g_uu"]))
        for r in laplace_results
    )
    print(f"  Max |Laplace residual|: {max_laplace:.6e}")
    if max_comp > 0:
        print(f"  Max relative residual: {max_laplace / max_comp:.6e}")

    # Generate gnuplot visualization
    print("Generating density model visualization with gnuplot...")
    nx = config["prism_grid"]["nx"]
    ny = config["prism_grid"]["ny"]
    nz = config["prism_grid"]["nz"]

    # Write data files for gnuplot — one matrix file per depth layer
    for iz in range(nz):
        with open(f"/app/layer_{iz}.dat", "w") as f:
            for iy in range(ny):
                row = []
                for ix in range(nx):
                    idx = iz * ny * nx + iy * nx + ix
                    row.append(f"{densities[idx]:.2f}")
                f.write(" ".join(row) + "\n")

    # Write gnuplot script
    z_min = config["prism_grid"]["z_min"]
    z_max = config["prism_grid"]["z_max"]
    dz = (z_max - z_min) / nz

    gp_script_lines = [
        "set terminal pngcairo size 900,400 enhanced font 'DejaVu Sans,10'",
        "set output '/app/density_model.png'",
        "",
        "set multiplot layout 1,2 title 'Recovered Density Model' font 'DejaVu Sans,12'",
        "",
        "set xlabel 'Easting Index'",
        "set ylabel 'Northing Index'",
        "set cblabel 'kg/m^3'",
        "set palette defined (0 'white', 150 '#ffffb2', 300 '#fecc5c', 450 '#fd8d3c', 600 '#e31a1c')",
        "set cbrange [0:700]",
        "",
    ]
    for iz in range(nz):
        layer_bot = z_min + iz * dz
        layer_top = z_min + (iz + 1) * dz
        gp_script_lines.extend([
            f"set title 'Layer {iz}: z = [{layer_bot:.0f}, {layer_top:.0f}] m'",
            f"plot '/app/layer_{iz}.dat' matrix with image notitle",
            "",
        ])
    gp_script_lines.append("unset multiplot")

    gp_script = "\n".join(gp_script_lines) + "\n"
    with open("/app/plot_density.gp", "w") as f:
        f.write(gp_script)

    result = subprocess.run(
        ["gnuplot", "/app/plot_density.gp"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"gnuplot stderr: {result.stderr}")
        raise RuntimeError(f"gnuplot failed with exit code {result.returncode}")

    print("Wrote /app/density_model.png")
    print("Done.")


if __name__ == "__main__":
    main()
