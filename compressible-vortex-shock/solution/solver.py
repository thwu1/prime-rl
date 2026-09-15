#!/usr/bin/env python3

"""
Reference solver for compressible vortex-shock interaction on a Gmsh mesh.

Generates the mesh using Gmsh CLI, parses the MSH 2.2 format, computes the
analytical flow field at all mesh nodes and element centroids, and writes
results.json and solution.msh with NodeData sections.
"""

import json
import math
import os
import subprocess
import sys

import numpy as np

# =========================================================
# Physical parameters
# =========================================================
GAMMA = 1.4
R_GAS = 1.0
M_S = 2.5
M_V = 0.8
RHO_U = 1.0
P_U = 1.0
T_U = P_U / (RHO_U * R_GAS)
U_U = M_S * math.sqrt(GAMMA * R_GAS * T_U)
V_U = 0.0

X_SHOCK = 0.5
X_C = 0.25
Y_C = 0.5
A = 0.075
B = 0.175
V_M = M_V * math.sqrt(GAMMA)

# =========================================================
# Rankine-Hugoniot downstream state
# =========================================================
MS2 = M_S * M_S
RHO_D = RHO_U * (GAMMA + 1.0) * MS2 / (2.0 + (GAMMA - 1.0) * MS2)
U_D = U_U * (2.0 + (GAMMA - 1.0) * MS2) / ((GAMMA + 1.0) * MS2)
P_D = P_U * (1.0 + 2.0 * GAMMA / (GAMMA + 1.0) * (MS2 - 1.0))
T_D = P_D / (RHO_D * R_GAS)

# =========================================================
# Precomputed vortex constants
# =========================================================
A2 = A * A
B2 = B * B
A2_B2 = A2 - B2
FAC = V_M * A / A2_B2
FAC2 = FAC * FAC
GM1_GR = (GAMMA - 1.0) / (R_GAS * GAMMA)

_RT_A = (-2.0 * B2 * math.log(B) - 0.5 * A2
         + 2.0 * B2 * math.log(A) + 0.5 * B2 * B2 / A2)
T_AT_A = T_U - GM1_GR * FAC2 * _RT_A


def compute_field(x, y):
    """Compute complete flow field at a single point."""
    if x <= X_SHOCK:
        p, t, u, v = P_U, T_U, U_U, V_U
    else:
        p, t, u, v = P_D, T_D, U_D, V_U

    dx = x - X_C
    dy = y - Y_C
    r = math.sqrt(dx * dx + dy * dy)

    if r <= B and r > 1e-15:
        sin_th = dy / r
        cos_th = dx / r

        if r <= A:
            mag = V_M * r / A
            u -= mag * sin_th
            v += mag * cos_th
            rt_core = 0.5 * (1.0 - r * r / A2)
            t = T_AT_A - GM1_GR * V_M * V_M * rt_core
        else:
            mag = V_M * A * (r - B2 / r) / A2_B2
            u -= mag * sin_th
            v += mag * cos_th
            rt = (-2.0 * B2 * math.log(B)
                  - 0.5 * r * r
                  + 2.0 * B2 * math.log(r)
                  + 0.5 * B2 * B2 / (r * r))
            t = T_U - GM1_GR * FAC2 * rt

        p = P_U * math.pow(t / T_U, GAMMA / (GAMMA - 1.0))

    rho = p / (R_GAS * t)
    c = math.sqrt(GAMMA * R_GAS * t)
    mach = math.sqrt(u * u + v * v) / c
    return {"rho": rho, "u": u, "v": v, "p": p, "T": t, "mach": mach}


def parse_msh2(filename):
    """Parse Gmsh MSH 2.2 format, return nodes and quad elements."""
    nodes = {}
    quads = []
    with open(filename) as f:
        while True:
            line = f.readline()
            if not line:
                break
            line = line.strip()
            if line == "$Nodes":
                n = int(f.readline().strip())
                for _ in range(n):
                    parts = f.readline().split()
                    nid = int(parts[0])
                    x, y = float(parts[1]), float(parts[2])
                    nodes[nid] = (x, y)
                f.readline()  # $EndNodes
            elif line == "$Elements":
                n = int(f.readline().strip())
                for _ in range(n):
                    parts = f.readline().split()
                    etype = int(parts[1])
                    ntags = int(parts[2])
                    if etype == 3:  # 4-node quad
                        nids = [int(p) for p in parts[3 + ntags:]]
                        quads.append(nids)
                f.readline()  # $EndElements
    return nodes, quads


def quad_area(coords):
    """Area of a quad using the shoelace formula."""
    n = len(coords)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += coords[i][0] * coords[j][1]
        area -= coords[j][0] * coords[i][1]
    return abs(area) / 2.0


def main():
    os.chdir("/app")

    # ---- Generate mesh ----
    print("Generating mesh with Gmsh...")
    ret = subprocess.run(
        ["gmsh", "domain.geo", "-2", "-format", "msh2", "-o", "mesh.msh", "-v", "0"],
        capture_output=True, text=True
    )
    if ret.returncode != 0:
        print("Gmsh error:", ret.stderr, file=sys.stderr)
        sys.exit(1)

    # ---- Parse mesh ----
    nodes, quads = parse_msh2("mesh.msh")
    print(f"Mesh: {len(nodes)} nodes, {len(quads)} quad elements")

    # ---- Compute field at all nodes ----
    node_fields = {}
    for nid, (x, y) in nodes.items():
        node_fields[nid] = compute_field(x, y)

    # ---- Compute element integrals and extrema ----
    total_mass = 0.0
    total_ke = 0.0
    max_mach = 0.0
    min_pressure = float("inf")

    for enodes in quads:
        coords = [nodes[n] for n in enodes]
        area = quad_area(coords)
        cx = sum(c[0] for c in coords) / 4.0
        cy = sum(c[1] for c in coords) / 4.0
        f = compute_field(cx, cy)
        total_mass += f["rho"] * area
        total_ke += 0.5 * f["rho"] * (f["u"] ** 2 + f["v"] ** 2) * area
        if f["mach"] > max_mach:
            max_mach = f["mach"]
        if f["p"] < min_pressure:
            min_pressure = f["p"]

    # ---- Probe points ----
    probe_coords = [
        (0.80, 0.50), (0.10, 0.20), (0.255, 0.50),
        (0.32, 0.50), (0.25, 0.42), (0.10, 0.50), (0.45, 0.50),
    ]
    probes = []
    for px, py in probe_coords:
        f = compute_field(px, py)
        probes.append({"x": px, "y": py, **f})

    # ---- Write results.json ----
    results = {
        "shock_density_ratio": RHO_D / RHO_U,
        "shock_pressure_ratio": P_D / P_U,
        "shock_temperature_ratio": T_D / T_U,
        "probe_points": probes,
        "total_mass": total_mass,
        "total_kinetic_energy": total_ke,
        "max_mach": max_mach,
        "min_pressure": min_pressure,
        "num_nodes": len(nodes),
        "num_elements": len(quads),
    }
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)

    # ---- Write solution.msh with NodeData ----
    with open("mesh.msh") as f:
        mesh_text = f.read()

    with open("solution.msh", "w") as f:
        f.write(mesh_text)
        for field_name in ["rho", "u", "v", "p", "T", "mach"]:
            f.write("$NodeData\n")
            f.write("1\n")
            f.write(f'"{field_name}"\n')
            f.write("1\n")
            f.write("0.0\n")
            f.write("3\n")
            f.write("0\n")
            f.write("1\n")
            f.write(f"{len(nodes)}\n")
            for nid in sorted(nodes.keys()):
                f.write(f"{nid} {node_fields[nid][field_name]:.15e}\n")
            f.write("$EndNodeData\n")

    print("Done. Written results.json and solution.msh")
    print(f"  shock_density_ratio  = {results['shock_density_ratio']:.10f}")
    print(f"  shock_pressure_ratio = {results['shock_pressure_ratio']:.10f}")
    print(f"  total_mass           = {total_mass:.10f}")
    print(f"  max_mach             = {max_mach:.10f}")
    print(f"  min_pressure         = {min_pressure:.10f}")


if __name__ == "__main__":
    main()
