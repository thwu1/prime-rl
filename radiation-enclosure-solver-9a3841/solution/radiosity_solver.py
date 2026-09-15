#!/usr/bin/env python3
"""Process a single enclosure: compute VFs via Node.js, solve radiosity, write to SQLite.

Usage: python3 radiosity_solver.py <enclosure.json> <results.db>
"""

import json
import math
import sqlite3
import subprocess
import sys

import numpy as np

SIGMA = 5.670374419e-8


def call_vfcalc(queries):
    """Call vfcalc.js with a batch of queries via stdin/stdout JSON."""
    proc = subprocess.run(
        ["node", "/app/catalog/vfcalc.js"],
        input=json.dumps(queries),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"vfcalc.js failed: {proc.stderr}")
    return json.loads(proc.stdout)


def process_box(config):
    """Compute VFs for a rectangular box enclosure."""
    Lx = config["length_x"]
    Ly = config["width_y"]
    Lz = config["height_z"]

    names = ["floor", "ceiling", "front", "back", "left", "right"]
    areas = {
        "floor": Lx * Ly, "ceiling": Lx * Ly,
        "front": Lx * Lz, "back": Lx * Lz,
        "left": Ly * Lz, "right": Ly * Lz,
    }

    # Batch VF queries: 3 opposed pairs (C-11), 3 adjacent pairs (C-14)
    queries = [
        {"formula": "C-11", "a": Lx, "b": Ly, "c": Lz},
        {"formula": "C-11", "a": Lx, "b": Lz, "c": Ly},
        {"formula": "C-11", "a": Ly, "b": Lz, "c": Lx},
        {"formula": "C-14", "w": Ly, "h": Lz, "l": Lx},
        {"formula": "C-14", "w": Lx, "h": Lz, "l": Ly},
        {"formula": "C-14", "w": Lx, "h": Ly, "l": Lz},
    ]
    results = call_vfcalc(queries)

    F = {}
    # Opposed pairs (symmetric)
    F[("floor", "ceiling")] = results[0]["F12"]
    F[("ceiling", "floor")] = results[0]["F12"]
    F[("front", "back")] = results[1]["F12"]
    F[("back", "front")] = results[1]["F12"]
    F[("left", "right")] = results[2]["F12"]
    F[("right", "left")] = results[2]["F12"]

    # Adjacent: floor/ceiling <-> front/back (common edge = Lx)
    vf_fb = results[3]["F12"]
    for s1, s2 in [("floor", "front"), ("floor", "back"),
                    ("ceiling", "front"), ("ceiling", "back")]:
        F[(s1, s2)] = vf_fb

    # Adjacent: floor/ceiling <-> left/right (common edge = Ly)
    vf_fl = results[4]["F12"]
    for s1, s2 in [("floor", "left"), ("floor", "right"),
                    ("ceiling", "left"), ("ceiling", "right")]:
        F[(s1, s2)] = vf_fl

    # Adjacent: front/back <-> left/right (common edge = Lz)
    vf_frl = results[5]["F12"]
    for s1, s2 in [("front", "left"), ("front", "right"),
                    ("back", "left"), ("back", "right")]:
        F[(s1, s2)] = vf_frl

    # Reverse adjacent pairs via reciprocity
    for s1, s2 in [
        ("front", "floor"), ("front", "ceiling"),
        ("back", "floor"), ("back", "ceiling"),
        ("left", "floor"), ("left", "ceiling"),
        ("left", "front"), ("left", "back"),
        ("right", "floor"), ("right", "ceiling"),
        ("right", "front"), ("right", "back"),
    ]:
        F[(s1, s2)] = areas[s2] * F[(s2, s1)] / areas[s1]

    # Self-view factors (all zero for flat surfaces)
    for s in names:
        F[(s, s)] = 0.0

    return names, areas, F


def process_cylinder(config):
    """Compute VFs for a right circular cylinder enclosure."""
    r = config["radius"]
    h = config["height"]

    names = ["bottom", "top", "lateral"]
    A_disk = math.pi * r * r
    A_lat = 2 * math.pi * r * h
    areas = {"bottom": A_disk, "top": A_disk, "lateral": A_lat}

    results = call_vfcalc([{"formula": "C-40", "r": r, "a": h}])
    F_bt = results[0]["F12"]

    F = {}
    F[("bottom", "top")] = F_bt
    F[("top", "bottom")] = F_bt
    F[("bottom", "bottom")] = 0.0
    F[("top", "top")] = 0.0
    F[("bottom", "lateral")] = 1.0 - F_bt
    F[("top", "lateral")] = 1.0 - F_bt

    F_ld = A_disk * (1.0 - F_bt) / A_lat
    F[("lateral", "bottom")] = F_ld
    F[("lateral", "top")] = F_ld
    F[("lateral", "lateral")] = 1.0 - 2 * F_ld

    return names, areas, F


def process_spheres(config):
    """Compute VFs for concentric spheres enclosure."""
    r1 = config["inner_radius"]
    r2 = config["outer_radius"]

    names = ["inner", "outer"]
    A1 = 4 * math.pi * r1 * r1
    A2 = 4 * math.pi * r2 * r2
    areas = {"inner": A1, "outer": A2}

    results = call_vfcalc([{"formula": "C-135", "r1": r1, "r2": r2}])

    F = {}
    F[("inner", "inner")] = 0.0
    F[("inner", "outer")] = results[0]["F12"]
    F[("outer", "inner")] = results[0]["F21"]
    F[("outer", "outer")] = results[0]["F22"]

    return names, areas, F


def solve_radiosity(names, areas, F, surfaces_cfg):
    """Build and solve the radiosity linear system."""
    N = len(names)
    props = {s["name"]: s for s in surfaces_cfg}

    A = np.zeros((N, N))
    b = np.zeros(N)

    for i, si in enumerate(names):
        eps = props[si]["emissivity"]
        cond = props[si]["condition"]
        val = props[si]["value"]

        if cond == "temperature":
            if abs(eps - 1.0) < 1e-15:
                # Blackbody: J_i = sigma * T^4
                A[i, :] = 0.0
                A[i, i] = 1.0
                b[i] = SIGMA * val ** 4
            else:
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
                G = sum(F.get((si, sj), 0.0) * J[j]
                        for j, sj in enumerate(names))
                heat_fluxes[si] = float(J[i] - G)
            else:
                heat_fluxes[si] = float(
                    eps / (1 - eps) * (SIGMA * val ** 4 - J[i])
                )
        else:
            heat_fluxes[si] = float(val)
            G = sum(F.get((si, sj), 0.0) * J[j]
                    for j, sj in enumerate(names))
            sigma_T4 = (J[i] - (1 - eps) * G) / eps
            eq_temps[si] = float((sigma_T4 / SIGMA) ** 0.25)

    return radiosities, heat_fluxes, eq_temps


def main():
    config_path = sys.argv[1]
    db_path = sys.argv[2]

    with open(config_path) as f:
        config = json.load(f)

    enc_type = config["type"]
    if enc_type == "rectangular_box":
        names, areas, F = process_box(config)
    elif enc_type == "cylinder":
        names, areas, F = process_cylinder(config)
    elif enc_type == "concentric_spheres":
        names, areas, F = process_spheres(config)
    else:
        raise ValueError(f"Unknown enclosure type: {enc_type}")

    radiosities, heat_fluxes, eq_temps = solve_radiosity(
        names, areas, F, config["surfaces"]
    )

    # Write to SQLite
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    geom = {k: v for k, v in config.items()
            if k not in ("name", "type", "surfaces")}
    c.execute(
        "INSERT INTO enclosures (name, type, geometry) VALUES (?, ?, ?)",
        (config["name"], config["type"], json.dumps(geom)),
    )
    enc_id = c.lastrowid

    for si in names:
        for sj in names:
            val = F.get((si, sj), 0.0)
            c.execute(
                "INSERT INTO view_factors "
                "(enclosure_id, surface_from, surface_to, value) "
                "VALUES (?, ?, ?, ?)",
                (enc_id, si, sj, val),
            )

    props = {s["name"]: s for s in config["surfaces"]}
    for si in names:
        c.execute(
            "INSERT INTO surface_results "
            "(enclosure_id, name, area, emissivity, bc_type, bc_value, "
            "radiosity, net_heat_flux, equilibrium_temp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                enc_id, si, areas[si], props[si]["emissivity"],
                props[si]["condition"], props[si]["value"],
                radiosities[si], heat_fluxes[si], eq_temps.get(si),
            ),
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
