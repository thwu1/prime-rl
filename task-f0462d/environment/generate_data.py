"""
Generate synthetic gravity data for the prism inversion task.
This script runs during Docker build (stage 1) and is NOT included in the final image.
"""
import json
import math

G = 6.674e-11  # gravitational constant, m^3/(kg*s^2)


def safe_log(x, y, z, r):
    """Numerically safe ln(x + r) for the prism gravity kernel."""
    if r == 0.0:
        return 0.0
    if x < 0.0:
        if y == 0.0 and z == 0.0:
            return -math.log(-2.0 * x)
        return math.log((y * y + z * z) / (r - x))
    return math.log(x + r)


def safe_atan2(y, x):
    """Principal-value arctan(y/x) with safe handling at x=0."""
    if x != 0.0:
        return math.atan(y / x)
    if y > 0.0:
        return math.pi / 2.0
    if y < 0.0:
        return -math.pi / 2.0
    return 0.0


def kernel_u(e, n, u):
    """Kernel for the upward component of gravitational acceleration."""
    r = math.sqrt(e * e + n * n + u * u)
    return (
        e * safe_log(n, e, u, r)
        + n * safe_log(e, n, u, r)
        - u * safe_atan2(e * n, u * r)
    )


def gravity_u(obs_e, obs_n, obs_up, prism, density):
    """Vertical gravitational acceleration due to a rectangular prism."""
    w, ep, s, np_, bot, top = prism
    shifts_e = [w - obs_e, ep - obs_e]
    shifts_n = [s - obs_n, np_ - obs_n]
    shifts_up = [bot - obs_up, top - obs_up]
    result = 0.0
    for i in range(2):
        for j in range(2):
            for k in range(2):
                sign = (-1) ** (i + j + k)
                result += sign * kernel_u(shifts_e[i], shifts_n[j], shifts_up[k])
    return -G * density * result


def main():
    # Prism grid: 4x4x2 = 32 prisms
    nx, ny, nz = 4, 4, 2
    x_min, x_max = 0.0, 400.0
    y_min, y_max = 0.0, 400.0
    z_min, z_max = -200.0, 0.0

    dx = (x_max - x_min) / nx
    dy = (y_max - y_min) / ny
    dz = (z_max - z_min) / nz

    prisms = []
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                prisms.append([
                    x_min + ix * dx,
                    x_min + (ix + 1) * dx,
                    y_min + iy * dy,
                    y_min + (iy + 1) * dy,
                    z_min + iz * dz,
                    z_min + (iz + 1) * dz,
                ])

    # True density model (kg/m^3)
    # Bottom layer (iz=0): two isolated anomalies
    # Top layer (iz=1): broader connected anomaly
    true_densities = [
        # Bottom layer (iz=0), iy=0..3, ix=0..3
        0, 0, 0, 0,
        0, 400, 0, 0,
        0, 0, 600, 0,
        0, 0, 0, 0,
        # Top layer (iz=1), iy=0..3, ix=0..3
        0, 0, 0, 0,
        0, 250, 350, 0,
        0, 200, 500, 0,
        0, 0, 100, 0,
    ]

    # Observation grid: 8x8 at z=50m
    obs_coords = []
    for iy_obs in range(8):
        for ix_obs in range(8):
            obs_coords.append({
                "easting": 25.0 + ix_obs * 50.0,
                "northing": 25.0 + iy_obs * 50.0,
                "upward": 50.0,
            })

    # Compute observed g_u at each observation point
    observations = []
    for obs in obs_coords:
        g_u_total = 0.0
        for p_idx, prism in enumerate(prisms):
            if true_densities[p_idx] != 0:
                g_u_total += gravity_u(
                    obs["easting"], obs["northing"], obs["upward"],
                    prism, true_densities[p_idx]
                )
        observations.append({
            "easting": obs["easting"],
            "northing": obs["northing"],
            "upward": obs["upward"],
            "g_u": g_u_total,
        })

    # Laplace test points: 4x4 grid at z=80m
    laplace_points = []
    for ly in [50.0, 150.0, 250.0, 350.0]:
        for lx in [50.0, 150.0, 250.0, 350.0]:
            laplace_points.append({
                "easting": lx,
                "northing": ly,
                "upward": 80.0,
            })

    # Write problem config
    config = {
        "prisms": prisms,
        "prism_grid": {
            "nx": nx, "ny": ny, "nz": nz,
            "x_min": x_min, "x_max": x_max,
            "y_min": y_min, "y_max": y_max,
            "z_min": z_min, "z_max": z_max,
        },
        "prism_indexing": "index = iz * ny * nx + iy * nx + ix (iz=layer, iy=northing, ix=easting)",
        "prism_format": "[west, east, south, north, bottom, top] in meters",
        "gravitational_constant": G,
        "laplace_test_points": laplace_points,
    }
    with open("/tmp/problem_config.json", "w") as f:
        json.dump(config, f, indent=2)

    # Write observed gravity
    obs_output = {
        "observations": observations,
        "units": "SI (m/s^2)",
        "field": "g_u: vertical (upward) component of gravitational acceleration",
    }
    with open("/tmp/observed_gravity.json", "w") as f:
        json.dump(obs_output, f, indent=2)

    # Diagnostics
    g_u_vals = [abs(o["g_u"]) for o in observations]
    print(f"Generated {len(prisms)} prisms, {len(observations)} observations")
    print(f"Non-zero density prisms: {sum(1 for d in true_densities if d != 0)}")
    print(f"|g_u| range: [{min(g_u_vals):.6e}, {max(g_u_vals):.6e}] m/s^2")


if __name__ == "__main__":
    main()
