#!/usr/bin/env python3
"""Gray-diffuse enclosure radiation heat transfer solver.

Reads an enclosure specification (rectangular box or cylinder) from a JSON
file, computes view factors using Howell's catalog closed-form formulas,
solves the radiosity linear system, and writes results to /app/results.json.
"""

import json
import math
import sys

import numpy as np

SIGMA = 5.670374419e-8  # Stefan-Boltzmann constant  [W / (m^2 K^4)]


# -----------------------------------------------------------------------
# View-factor formulas from Howell's catalog
# -----------------------------------------------------------------------

def vf_parallel_rectangles(a: float, b: float, c: float) -> float:
    """C-11: Identical, parallel, directly opposed rectangles.

    Parameters
    ----------
    a, b : rectangle side lengths (both rectangles are a x b).
    c    : perpendicular separation distance.

    Returns F_{1->2}.
    """
    X = a / c
    Y = b / c
    X2, Y2 = X * X, Y * Y

    t1 = math.log(math.sqrt((1 + X2) * (1 + Y2) / (1 + X2 + Y2)))
    t2 = X * math.sqrt(1 + Y2) * math.atan(X / math.sqrt(1 + Y2))
    t3 = Y * math.sqrt(1 + X2) * math.atan(Y / math.sqrt(1 + X2))
    t4 = -X * math.atan(X)
    t5 = -Y * math.atan(Y)

    return 2.0 / (math.pi * X * Y) * (t1 + t2 + t3 + t4 + t5)


def vf_perpendicular_rectangles(w: float, h: float, l: float) -> float:
    """C-14: Two perpendicular rectangles sharing a common edge of length *l*.

    Surface 1 is l x w  (depth w perpendicular to the common edge).
    Surface 2 is l x h  (depth h perpendicular to the common edge).

    Returns F_{1->2}.
    """
    W = w / l
    H = h / l
    W2, H2 = W * W, H * H

    t1 = W * math.atan(1.0 / W)
    t2 = H * math.atan(1.0 / H)
    t3 = -math.sqrt(H2 + W2) * math.atan(1.0 / math.sqrt(H2 + W2))

    base = (1 + W2) * (1 + H2) / (1 + W2 + H2)
    f_W = (W2 * (1 + W2 + H2) / ((1 + W2) * (W2 + H2))) ** W2
    f_H = (H2 * (1 + H2 + W2) / ((1 + H2) * (W2 + H2))) ** H2
    t4 = 0.25 * math.log(base * f_W * f_H)

    return (t1 + t2 + t3 + t4) / (W * math.pi)


def vf_coaxial_equal_disks(r: float, a: float) -> float:
    """C-40: Two coaxial disks of equal radius.

    Parameters
    ----------
    r : disk radius.
    a : axial separation distance.

    Returns F_{1->2}.
    """
    R = r / a
    X = (2 * R * R + 1) / (R * R)
    return 0.5 * (X - math.sqrt(X * X - 4))


# -----------------------------------------------------------------------
# Geometry: rectangular box
# -----------------------------------------------------------------------

def compute_box(config: dict):
    """Return (surface_names, areas, F) for a rectangular box."""
    Lx = config["length_x"]
    Ly = config["width_y"]
    Lz = config["height_z"]

    names = ["floor", "ceiling", "front", "back", "left", "right"]
    areas = {
        "floor": Lx * Ly, "ceiling": Lx * Ly,
        "front": Lx * Lz, "back":    Lx * Lz,
        "left":  Ly * Lz, "right":   Ly * Lz,
    }

    F = {}

    # --- opposed pairs (C-11) ---
    F[("floor", "ceiling")] = vf_parallel_rectangles(Lx, Ly, Lz)
    F[("ceiling", "floor")] = F[("floor", "ceiling")]

    F[("front", "back")] = vf_parallel_rectangles(Lx, Lz, Ly)
    F[("back", "front")] = F[("front", "back")]

    F[("left", "right")] = vf_parallel_rectangles(Ly, Lz, Lx)
    F[("right", "left")] = F[("left", "right")]

    # --- adjacent pairs (C-14) ---
    # floor/ceiling <-> front/back:  common edge = Lx
    vf_fb = vf_perpendicular_rectangles(Ly, Lz, Lx)
    F[("floor", "front")]   = vf_fb
    F[("floor", "back")]    = vf_fb
    F[("ceiling", "front")] = vf_fb
    F[("ceiling", "back")]  = vf_fb

    # floor/ceiling <-> left/right:  common edge = Ly
    vf_fl = vf_perpendicular_rectangles(Lx, Lz, Ly)
    F[("floor", "left")]    = vf_fl
    F[("floor", "right")]   = vf_fl
    F[("ceiling", "left")]  = vf_fl
    F[("ceiling", "right")] = vf_fl

    # front/back <-> left/right:  common edge = Lz
    vf_frl = vf_perpendicular_rectangles(Lx, Ly, Lz)
    F[("front", "left")]  = vf_frl
    F[("front", "right")] = vf_frl
    F[("back", "left")]   = vf_frl
    F[("back", "right")]  = vf_frl

    # --- reverse adjacent pairs via reciprocity ---
    for si, sj in [
        ("front", "floor"), ("front", "ceiling"),
        ("back", "floor"),  ("back", "ceiling"),
        ("left", "floor"),  ("left", "ceiling"),
        ("left", "front"),  ("left", "back"),
        ("right", "floor"), ("right", "ceiling"),
        ("right", "front"), ("right", "back"),
    ]:
        F[(si, sj)] = areas[sj] * F[(sj, si)] / areas[si]

    return names, areas, F


# -----------------------------------------------------------------------
# Geometry: right circular cylinder
# -----------------------------------------------------------------------

def compute_cylinder(config: dict):
    """Return (surface_names, areas, F) for a cylinder."""
    r = config["radius"]
    h = config["height"]

    names = ["bottom", "top", "lateral"]
    A_disk = math.pi * r * r
    A_lat = 2 * math.pi * r * h
    areas = {"bottom": A_disk, "top": A_disk, "lateral": A_lat}

    F = {}

    # bottom <-> top  (C-40)
    F_bt = vf_coaxial_equal_disks(r, h)
    F[("bottom", "top")] = F_bt
    F[("top", "bottom")] = F_bt

    # bottom/top -> lateral  (summation:  F_self=0 for flat disk)
    F[("bottom", "lateral")] = 1.0 - F_bt
    F[("top", "lateral")]    = 1.0 - F_bt

    # lateral -> bottom/top  (reciprocity)
    F_ld = A_disk * (1.0 - F_bt) / A_lat
    F[("lateral", "bottom")] = F_ld
    F[("lateral", "top")]    = F_ld

    # lateral -> lateral  (summation)
    F[("lateral", "lateral")] = 1.0 - 2 * F_ld

    return names, areas, F


# -----------------------------------------------------------------------
# Radiosity solver
# -----------------------------------------------------------------------

def solve_radiosity(names, areas, F, surfaces_cfg):
    """Build and solve the radiosity linear system.

    Returns (radiosities, net_heat_fluxes, equilibrium_temperatures).
    """
    N = len(names)
    props = {s["name"]: s for s in surfaces_cfg}

    # Assemble  A * J = b
    A = np.zeros((N, N))
    b = np.zeros(N)

    for i, si in enumerate(names):
        eps = props[si]["emissivity"]
        cond = props[si]["condition"]
        val = props[si]["value"]

        if cond == "temperature":
            for j, sj in enumerate(names):
                fij = F.get((si, sj), 0.0)
                if i == j:
                    A[i, j] = 1.0 - (1 - eps) * fij
                else:
                    A[i, j] = -(1 - eps) * fij
            b[i] = eps * SIGMA * val ** 4

        else:  # heatflux
            for j, sj in enumerate(names):
                fij = F.get((si, sj), 0.0)
                if i == j:
                    A[i, j] = 1.0 - fij
                else:
                    A[i, j] = -fij
            b[i] = val

    J = np.linalg.solve(A, b)

    # --- derive outputs ---
    radiosities = {}
    heat_fluxes = {}
    eq_temps = {}

    for i, si in enumerate(names):
        radiosities[si] = float(J[i])
        eps = props[si]["emissivity"]
        cond = props[si]["condition"]
        val = props[si]["value"]

        if cond == "temperature":
            if abs(eps - 1.0) < 1e-15:
                # blackbody: q = J - G
                G = sum(F.get((si, sj), 0.0) * J[j]
                        for j, sj in enumerate(names))
                heat_fluxes[si] = float(J[i] - G)
            else:
                heat_fluxes[si] = float(
                    eps / (1 - eps) * (SIGMA * val ** 4 - J[i])
                )
        else:  # heatflux
            heat_fluxes[si] = float(val)
            G = sum(F.get((si, sj), 0.0) * J[j]
                    for j, sj in enumerate(names))
            sigma_T4 = (J[i] - (1 - eps) * G) / eps
            eq_temps[si] = float((sigma_T4 / SIGMA) ** 0.25)

    return radiosities, heat_fluxes, eq_temps


# -----------------------------------------------------------------------
# Main entry point
# -----------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 radsolve.py <enclosure.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = json.load(f)

    enc_type = config["type"]
    if enc_type == "rectangular_box":
        names, areas, F = compute_box(config)
    elif enc_type == "cylinder":
        names, areas, F = compute_cylinder(config)
    else:
        raise ValueError(f"Unknown enclosure type: {enc_type}")

    radiosities, heat_fluxes, eq_temps = solve_radiosity(
        names, areas, F, config["surfaces"]
    )

    # Build view-factor output dict
    vf_out = {}
    for si in names:
        for sj in names:
            key = f"{si}->{sj}"
            val = F.get((si, sj), 0.0)
            if val != 0.0 or si != sj:
                vf_out[key] = val

    results = {
        "view_factors": vf_out,
        "radiosities": radiosities,
        "net_heat_fluxes": heat_fluxes,
        "equilibrium_temperatures": eq_temps,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
