#!/usr/bin/env python3
"""Run a rotation library through the benchmark suite and store results in SQLite.

Usage: python3 run_benchmark.py <library_name>
  where library_name is one of: alpha, beta, gamma

Results are stored in the benchmark_results table of /app/rotations.db.
"""

import sys
import importlib
import sqlite3
import numpy as np

DB_PATH = "/app/rotations.db"

LIBRARY_MAP = {
    "alpha": "lib_alpha",
    "beta": "lib_beta",
    "gamma": "lib_gamma",
}


def quaternion_error(q_pred, q_expected):
    """Minimum of ||q_pred - q_exp|| and ||q_pred + q_exp|| (double cover)."""
    q_pred = np.asarray(q_pred, dtype=float)
    q_expected = np.asarray(q_expected, dtype=float)
    q_pred = q_pred / np.linalg.norm(q_pred)
    q_expected = q_expected / np.linalg.norm(q_expected)
    return min(np.linalg.norm(q_pred - q_expected),
               np.linalg.norm(q_pred + q_expected))


def matrix_error(R_pred, R_expected):
    """Frobenius norm of difference."""
    return np.linalg.norm(np.asarray(R_pred) - np.asarray(R_expected))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in LIBRARY_MAP:
        print(f"Usage: python3 {sys.argv[0]} <alpha|beta|gamma>")
        sys.exit(1)

    lib_name = sys.argv[1]
    module_name = LIBRARY_MAP[lib_name]

    sys.path.insert(0, "/app")
    lib = importlib.import_module(module_name)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Clear previous results for this library
    c.execute("DELETE FROM benchmark_results WHERE library = ?", (lib_name,))

    # --- Test quaternion_to_matrix ---
    print(f"[{lib_name}] Testing quaternion_to_matrix...")
    for row in c.execute("SELECT id, category, qw, qx, qy, qz, r00, r01, r02, r10, r11, r12, r20, r21, r22 FROM test_rotations").fetchall():
        tid, cat = row[0], row[1]
        q = np.array(row[2:6])
        R_expected = np.array(row[6:15]).reshape(3, 3)
        try:
            R_pred = lib.quaternion_to_matrix(q)
            err = matrix_error(R_pred, R_expected)
        except Exception:
            err = 999.0
        c.execute("INSERT INTO benchmark_results (library, func, test_id, category, error) VALUES (?,?,?,?,?)",
                  (lib_name, "quaternion_to_matrix", tid, cat, err))

    # --- Test matrix_to_quaternion ---
    print(f"[{lib_name}] Testing matrix_to_quaternion...")
    for row in c.execute("SELECT id, category, qw, qx, qy, qz, r00, r01, r02, r10, r11, r12, r20, r21, r22 FROM test_rotations").fetchall():
        tid, cat = row[0], row[1]
        q_expected = np.array(row[2:6])
        R = np.array(row[6:15]).reshape(3, 3)
        try:
            q_pred = lib.matrix_to_quaternion(R)
            err = quaternion_error(q_pred, q_expected)
        except Exception:
            err = 999.0
        c.execute("INSERT INTO benchmark_results (library, func, test_id, category, error) VALUES (?,?,?,?,?)",
                  (lib_name, "matrix_to_quaternion", tid, cat, err))

    # --- Test axis_angle_to_matrix ---
    print(f"[{lib_name}] Testing axis_angle_to_matrix...")
    for row in c.execute("SELECT id, category, ax, ay, az, r00, r01, r02, r10, r11, r12, r20, r21, r22 FROM test_rotations").fetchall():
        tid, cat = row[0], row[1]
        aa = np.array(row[2:5])
        R_expected = np.array(row[5:14]).reshape(3, 3)
        try:
            R_pred = lib.axis_angle_to_matrix(aa)
            err = matrix_error(R_pred, R_expected)
        except Exception:
            err = 999.0
        c.execute("INSERT INTO benchmark_results (library, func, test_id, category, error) VALUES (?,?,?,?,?)",
                  (lib_name, "axis_angle_to_matrix", tid, cat, err))

    # --- Test matrix_to_euler_angles ---
    print(f"[{lib_name}] Testing matrix_to_euler_angles...")
    for row in c.execute("SELECT id, category, r00, r01, r02, r10, r11, r12, r20, r21, r22, ex, ey, ez FROM test_rotations").fetchall():
        tid, cat = row[0], row[1]
        R = np.array(row[2:11]).reshape(3, 3)
        euler_expected = np.array(row[11:14])
        try:
            euler_pred = lib.matrix_to_euler_angles(R, "XYZ")
            err = np.linalg.norm(euler_pred - euler_expected)
        except Exception:
            err = 999.0
        c.execute("INSERT INTO benchmark_results (library, func, test_id, category, error) VALUES (?,?,?,?,?)",
                  (lib_name, "matrix_to_euler_angles", tid, cat, err))

    # --- Test geodesic_distance ---
    print(f"[{lib_name}] Testing geodesic_distance...")
    for row in c.execute("SELECT id, category, a00,a01,a02,a10,a11,a12,a20,a21,a22, b00,b01,b02,b10,b11,b12,b20,b21,b22, expected FROM test_geodesic").fetchall():
        tid, cat = row[0], row[1]
        R1 = np.array(row[2:11]).reshape(3, 3)
        R2 = np.array(row[11:20]).reshape(3, 3)
        expected = row[20]
        try:
            pred = lib.geodesic_distance(R1, R2)
            err = abs(pred - expected)
        except Exception:
            err = 999.0
        c.execute("INSERT INTO benchmark_results (library, func, test_id, category, error) VALUES (?,?,?,?,?)",
                  (lib_name, "geodesic_distance", tid, cat, err))

    # --- Test slerp ---
    print(f"[{lib_name}] Testing slerp...")
    for row in c.execute("SELECT id, category, q0w,q0x,q0y,q0z, q1w,q1x,q1y,q1z, t, ew,ex,ey,ez FROM test_slerp").fetchall():
        tid, cat = row[0], row[1]
        q0 = np.array(row[2:6])
        q1 = np.array(row[6:10])
        t = row[10]
        q_expected = np.array(row[11:15])
        try:
            q_pred = lib.slerp(q0, q1, t)
            err = quaternion_error(q_pred, q_expected)
        except Exception:
            err = 999.0
        c.execute("INSERT INTO benchmark_results (library, func, test_id, category, error) VALUES (?,?,?,?,?)",
                  (lib_name, "slerp", tid, cat, err))

    conn.commit()
    conn.close()

    print(f"\n[{lib_name}] Benchmark complete. Results stored in {DB_PATH}")
    print(f"Query with: sqlite3 {DB_PATH} \"SELECT func, MAX(error), AVG(error) FROM benchmark_results WHERE library='{lib_name}' GROUP BY func\"")


if __name__ == "__main__":
    main()
