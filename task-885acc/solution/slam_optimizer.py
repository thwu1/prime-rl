#!/usr/bin/env python3
"""
Pose graph optimizer: reads from SQLite, uses compiled SE(2) C library via
ctypes, implements Gauss-Newton with Cauchy robust kernel.
"""

import ctypes
import json
import math
import os
import sqlite3
import struct
import subprocess

import numpy as np


def normalize_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def build_se2_lib():
    """Compile the SE(2) shared library and load it."""
    tools_dir = "/app/tools"
    subprocess.run(["make", "-C", tools_dir, "-s"], check=True)
    lib = ctypes.CDLL(os.path.join(tools_dir, "libse2.so"))

    c_double_p = ctypes.POINTER(ctypes.c_double)

    lib.se2_edge_error.argtypes = [ctypes.c_double] * 9 + [c_double_p] * 3
    lib.se2_edge_error.restype = None

    lib.se2_normalize_angle.argtypes = [ctypes.c_double]
    lib.se2_normalize_angle.restype = ctypes.c_double

    return lib


def read_pose_graph(db_path):
    """Read pose graph from SQLite database, unpacking binary BLOBs."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    nodes = []
    for row in c.execute("SELECT id, x, y, theta FROM nodes ORDER BY id"):
        nodes.append({"id": row[0], "x": row[1], "y": row[2], "theta": row[3]})

    edges = []
    for row in c.execute(
        "SELECT from_id, to_id, dx, dy, dtheta, info_matrix, edge_type FROM edges"
    ):
        info = list(struct.unpack('<6d', row[5]))
        edges.append({
            "from_id": row[0], "to_id": row[1],
            "dx": row[2], "dy": row[3], "dtheta": row[4],
            "information": info, "type": row[6],
        })

    conn.close()
    return {"nodes": nodes, "edges": edges}


def compute_error_with_lib(lib, xi, xj, zij):
    """Compute edge error using the compiled C library via ctypes."""
    ex = ctypes.c_double()
    ey = ctypes.c_double()
    et = ctypes.c_double()
    lib.se2_edge_error(
        float(xi[0]), float(xi[1]), float(xi[2]),
        float(xj[0]), float(xj[1]), float(xj[2]),
        float(zij[0]), float(zij[1]), float(zij[2]),
        ctypes.byref(ex), ctypes.byref(ey), ctypes.byref(et),
    )
    return np.array([ex.value, ey.value, et.value])


def compute_jacobians(xi, xj, zij):
    """Compute analytical Jacobians A (w.r.t. xi) and B (w.r.t. xj)."""
    ti = xi[2]
    ci, si = math.cos(ti), math.sin(ti)
    tz = zij[2]
    cz, sz = math.cos(tz), math.sin(tz)

    dx = xj[0] - xi[0]
    dy = xj[1] - xi[1]

    dd_dti = np.array([-si * dx + ci * dy, -ci * dx - si * dy])

    RzTRiT = np.array([
        [cz * ci - sz * si, cz * si + sz * ci],
        [-sz * ci - cz * si, -sz * si + cz * ci],
    ])

    A = np.zeros((3, 3))
    A[0:2, 0:2] = -RzTRiT
    A[0, 2] = cz * dd_dti[0] + sz * dd_dti[1]
    A[1, 2] = -sz * dd_dti[0] + cz * dd_dti[1]
    A[2, 2] = -1.0

    B = np.zeros((3, 3))
    B[0:2, 0:2] = RzTRiT
    B[2, 2] = 1.0

    return A, B


def info_from_upper_tri(ut):
    """Reconstruct full 3x3 symmetric matrix from upper triangle."""
    return np.array([
        [ut[0], ut[1], ut[2]],
        [ut[1], ut[3], ut[4]],
        [ut[2], ut[4], ut[5]],
    ])


def optimize(data, lib, cauchy_c=3.0, max_iter=100, tol=1e-6):
    nodes = data["nodes"]
    edges = data["edges"]
    N = len(nodes)
    dim = 3 * N
    c2 = cauchy_c ** 2

    x = np.zeros(dim)
    for node in nodes:
        k = node["id"]
        x[3 * k] = node["x"]
        x[3 * k + 1] = node["y"]
        x[3 * k + 2] = node["theta"]

    for iteration in range(max_iter):
        H = np.zeros((dim, dim))
        b = np.zeros(dim)

        for edge in edges:
            i = edge["from_id"]
            j = edge["to_id"]
            zij = np.array([edge["dx"], edge["dy"], edge["dtheta"]])
            omega = info_from_upper_tri(edge["information"])

            xi = x[3 * i:3 * i + 3]
            xj = x[3 * j:3 * j + 3]

            e = compute_error_with_lib(lib, xi, xj, zij)
            A, B = compute_jacobians(xi, xj, zij)

            # Cauchy robust weighting
            d2 = float(e @ omega @ e)
            d2 = max(d2, 1e-12)
            w = c2 / (c2 + d2)
            omega_w = w * omega

            AtO = A.T @ omega_w
            BtO = B.T @ omega_w

            H[3 * i:3 * i + 3, 3 * i:3 * i + 3] += AtO @ A
            H[3 * i:3 * i + 3, 3 * j:3 * j + 3] += AtO @ B
            H[3 * j:3 * j + 3, 3 * i:3 * i + 3] += BtO @ A
            H[3 * j:3 * j + 3, 3 * j:3 * j + 3] += BtO @ B

            b[3 * i:3 * i + 3] += AtO @ e
            b[3 * j:3 * j + 3] += BtO @ e

        # Anchor node 0
        H[0:3, 0:3] += 1e8 * np.eye(3)

        dx_vec = np.linalg.solve(H, -b)

        x += dx_vec
        for k in range(N):
            x[3 * k + 2] = normalize_angle(x[3 * k + 2])

        if np.linalg.norm(dx_vec) < tol:
            break

    return [
        {
            "id": k,
            "x": float(x[3 * k]),
            "y": float(x[3 * k + 1]),
            "theta": float(normalize_angle(x[3 * k + 2])),
        }
        for k in range(N)
    ]


def main():
    lib = build_se2_lib()
    data = read_pose_graph("/app/pose_graph.db")
    result = optimize(data, lib)
    with open("/app/result.json", "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
