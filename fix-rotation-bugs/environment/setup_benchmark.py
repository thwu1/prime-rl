"""Generate the rotation benchmark SQLite database with ground-truth test cases.

This script is run during Docker build and then deleted. It uses known-correct
implementations to compute ground truth values.
"""

import numpy as np
import sqlite3
import json

DB_PATH = "/app/rotations.db"

# ======================================================================
# Correct implementations for ground-truth computation (not exported)
# ======================================================================

def _correct_quaternion_to_matrix(q):
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w),     2*(x*z + y*w)],
        [2*(x*y + z*w),     1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w),     2*(y*z + x*w),      1 - 2*(x*x + y*y)]
    ])

def _correct_matrix_to_quaternion(R):
    m00, m01, m02 = R[0,0], R[0,1], R[0,2]
    m10, m11, m12 = R[1,0], R[1,1], R[1,2]
    m20, m21, m22 = R[2,0], R[2,1], R[2,2]
    trace = m00 + m11 + m22
    if trace > 0:
        s = 2.0 * np.sqrt(1.0 + trace)
        w, x, y, z = 0.25*s, (m21-m12)/s, (m02-m20)/s, (m10-m01)/s
    elif m00 > m11 and m00 > m22:
        s = 2.0 * np.sqrt(1.0 + m00 - m11 - m22)
        w, x, y, z = (m21-m12)/s, 0.25*s, (m01+m10)/s, (m02+m20)/s
    elif m11 > m22:
        s = 2.0 * np.sqrt(1.0 + m11 - m00 - m22)
        w, x, y, z = (m02-m20)/s, (m01+m10)/s, 0.25*s, (m12+m21)/s
    else:
        s = 2.0 * np.sqrt(1.0 + m22 - m00 - m11)
        w, x, y, z = (m10-m01)/s, (m02+m20)/s, (m12+m21)/s, 0.25*s
    q = np.array([w, x, y, z])
    q = q / np.linalg.norm(q)
    if q[0] < 0: q = -q
    return q

def _correct_axis_angle_to_matrix(aa):
    angle = np.linalg.norm(aa)
    if angle < 1e-10: return np.eye(3)
    axis = aa / angle
    K = np.array([[0,-axis[2],axis[1]], [axis[2],0,-axis[0]], [-axis[1],axis[0],0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)

def _correct_geodesic_distance(R1, R2):
    R_rel = R1 @ R2.T
    cos_a = np.clip((np.trace(R_rel) - 1) / 2.0, -1.0, 1.0)
    return float(np.arccos(cos_a))

def _correct_slerp(q0, q1, t):
    q0 = q0 / np.linalg.norm(q0)
    q1 = q1 / np.linalg.norm(q1)
    dot = np.dot(q0, q1)
    if dot < 0:
        q1 = -q1
        dot = -dot
    dot = np.clip(dot, -1.0, 1.0)
    theta = np.arccos(dot)
    if abs(theta) < 1e-10: return q0.copy()
    sin_t = np.sin(theta)
    result = np.sin((1-t)*theta)/sin_t * q0 + np.sin(t*theta)/sin_t * q1
    return result / np.linalg.norm(result)

def _idx(letter):
    return {"X": 0, "Y": 1, "Z": 2}[letter]

def _single_rot(axis, angle):
    c, s = np.cos(angle), np.sin(angle)
    if axis == "X": return np.array([[1,0,0],[0,c,-s],[0,s,c]], dtype=float)
    if axis == "Y": return np.array([[c,0,s],[0,1,0],[-s,0,c]], dtype=float)
    return np.array([[c,-s,0],[s,c,0],[0,0,1]], dtype=float)

def _correct_euler_to_matrix(angles, conv):
    return _single_rot(conv[0], angles[0]) @ _single_rot(conv[1], angles[1]) @ _single_rot(conv[2], angles[2])

def _angle_from_tan(axis, other_axis, data, horizontal, tait_bryan):
    i1, i2 = {"X": (2,1), "Y": (0,2), "Z": (1,0)}[axis]
    if horizontal: i2, i1 = i1, i2
    even = (axis + other_axis) in ["XY", "YZ", "ZX"]
    if horizontal == even: return np.arctan2(data[i1], data[i2])
    if tait_bryan: return np.arctan2(-data[i2], data[i1])
    return np.arctan2(data[i2], -data[i1])

def _correct_matrix_to_euler(R, conv):
    i0, i2 = _idx(conv[0]), _idx(conv[2])
    tb = i0 != i2
    if tb:
        ca = np.arcsin(np.clip(R[i0,i2], -1,1) * (-1.0 if i0-i2 in [-1,2] else 1.0))
    else:
        ca = np.arccos(np.clip(R[i0,i0], -1,1))
    return np.array([
        _angle_from_tan(conv[0], conv[1], R[:,i2], False, tb),
        ca,
        _angle_from_tan(conv[2], conv[1], R[i0,:], True, tb),
    ])


# ======================================================================
# Generate test cases and populate database
# ======================================================================

def make_quat(axis, angle_rad):
    """Create quaternion from axis and angle."""
    axis = np.array(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    h = angle_rad / 2.0
    return np.array([np.cos(h), *(np.sin(h) * axis)])

def standardize(q):
    q = q / np.linalg.norm(q)
    if q[0] < 0: q = -q
    return q


def main():
    np.random.seed(42)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE test_rotations (
        id INTEGER PRIMARY KEY, category TEXT,
        qw REAL, qx REAL, qy REAL, qz REAL,
        r00 REAL, r01 REAL, r02 REAL,
        r10 REAL, r11 REAL, r12 REAL,
        r20 REAL, r21 REAL, r22 REAL,
        ax REAL, ay REAL, az REAL,
        ex REAL, ey REAL, ez REAL
    )""")

    c.execute("""CREATE TABLE test_geodesic (
        id INTEGER PRIMARY KEY, category TEXT,
        a00 REAL, a01 REAL, a02 REAL,
        a10 REAL, a11 REAL, a12 REAL,
        a20 REAL, a21 REAL, a22 REAL,
        b00 REAL, b01 REAL, b02 REAL,
        b10 REAL, b11 REAL, b12 REAL,
        b20 REAL, b21 REAL, b22 REAL,
        expected REAL
    )""")

    c.execute("""CREATE TABLE test_slerp (
        id INTEGER PRIMARY KEY, category TEXT,
        q0w REAL, q0x REAL, q0y REAL, q0z REAL,
        q1w REAL, q1x REAL, q1y REAL, q1z REAL,
        t REAL,
        ew REAL, ex REAL, ey REAL, ez REAL
    )""")

    c.execute("""CREATE TABLE benchmark_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        library TEXT NOT NULL,
        func TEXT NOT NULL,
        test_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        error REAL NOT NULL
    )""")

    # --- Rotation test cases ---
    test_quats = []

    # Identity
    test_quats.append(("identity", np.array([1.0, 0, 0, 0])))

    # Small angles (1-5 degrees)
    for deg in [1, 3, 5]:
        axis = np.random.randn(3); axis /= np.linalg.norm(axis)
        test_quats.append(("small_angle", make_quat(axis, np.radians(deg))))

    # 90-degree axis-aligned
    for ax in [[1,0,0], [0,1,0], [0,0,1]]:
        test_quats.append(("axis_90", make_quat(ax, np.pi/2)))

    # 180-degree axis-aligned
    for ax in [[1,0,0], [0,1,0], [0,0,1]]:
        test_quats.append(("axis_180", make_quat(ax, np.pi)))

    # Moderate angles (30, 60, 90, 120 degrees around random axes)
    for deg in [30, 60, 90, 120]:
        axis = np.random.randn(3); axis /= np.linalg.norm(axis)
        test_quats.append(("moderate", make_quat(axis, np.radians(deg))))

    # 120-degree around (1,1,1) - cyclic permutation
    test_quats.append(("moderate", make_quat([1,1,1], 2*np.pi/3)))

    # General random rotations
    for _ in range(10):
        q = np.random.randn(4)
        q = q / np.linalg.norm(q)
        if q[0] < 0: q = -q
        test_quats.append(("general", q))

    # Near-180 rotations around non-axis-aligned directions
    for _ in range(3):
        axis = np.random.randn(3); axis /= np.linalg.norm(axis)
        test_quats.append(("near_180", make_quat(axis, np.radians(175))))

    rid = 0
    for category, q in test_quats:
        q = standardize(q)
        R = _correct_quaternion_to_matrix(q)
        # Compute axis-angle from quaternion
        w_val = q[0]
        xyz = q[1:]
        sh = np.linalg.norm(xyz)
        if sh < 1e-10:
            aa = np.zeros(3)
        else:
            angle = 2.0 * np.arctan2(sh, w_val)
            aa = angle * (xyz / sh)
        # Compute euler angles (XYZ)
        euler = _correct_matrix_to_euler(R, "XYZ")

        c.execute(
            "INSERT INTO test_rotations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, category,
             q[0], q[1], q[2], q[3],
             R[0,0], R[0,1], R[0,2],
             R[1,0], R[1,1], R[1,2],
             R[2,0], R[2,1], R[2,2],
             aa[0], aa[1], aa[2],
             euler[0], euler[1], euler[2])
        )
        rid += 1

    # --- Geodesic test cases ---
    geo_cases = []
    # Identity distance
    I = np.eye(3)
    geo_cases.append(("identity", I, I, 0.0))

    # Known distances
    R90z = np.array([[0,-1,0],[1,0,0],[0,0,1]], dtype=float)
    geo_cases.append(("axis_90", I, R90z, np.pi/2))

    R180x = np.diag([1.0, -1.0, -1.0])
    geo_cases.append(("axis_180", I, R180x, np.pi))

    R60z = _correct_axis_angle_to_matrix(np.array([0, 0, np.pi/3]))
    geo_cases.append(("moderate", I, R60z, np.pi/3))

    # Random pairs
    for _ in range(6):
        q1 = np.random.randn(4); q1 /= np.linalg.norm(q1)
        q2 = np.random.randn(4); q2 /= np.linalg.norm(q2)
        R1 = _correct_quaternion_to_matrix(q1)
        R2 = _correct_quaternion_to_matrix(q2)
        d = _correct_geodesic_distance(R1, R2)
        geo_cases.append(("general", R1, R2, d))

    gid = 0
    for category, R1, R2, expected in geo_cases:
        c.execute(
            "INSERT INTO test_geodesic VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (gid, category,
             R1[0,0], R1[0,1], R1[0,2],
             R1[1,0], R1[1,1], R1[1,2],
             R1[2,0], R1[2,1], R1[2,2],
             R2[0,0], R2[0,1], R2[0,2],
             R2[1,0], R2[1,1], R2[1,2],
             R2[2,0], R2[2,1], R2[2,2],
             expected)
        )
        gid += 1

    # --- SLERP test cases ---
    slerp_cases = []

    # Endpoints
    q0 = np.array([1.0, 0, 0, 0])
    q1 = make_quat([1, 0, 0], np.pi/3)
    slerp_cases.append(("endpoint", q0, q1, 0.0, q0))
    slerp_cases.append(("endpoint", q0, q1, 1.0, q1))

    # Midpoint of known rotation
    mid = _correct_slerp(q0, q1, 0.5)
    slerp_cases.append(("midpoint", q0, q1, 0.5, mid))

    # Shortest path cases (negative dot product)
    q0_sp = np.array([0.5, 0.5, 0.5, 0.5])
    q1_sp = np.array([0.5, -0.5, -0.5, -0.5])
    mid_sp = _correct_slerp(q0_sp, q1_sp, 0.5)
    slerp_cases.append(("shortest_path", q0_sp, q1_sp, 0.5, mid_sp))

    q0_sp2 = make_quat([0, 0, 1], np.pi/4)
    q1_sp2 = make_quat([0, 0, 1], -3*np.pi/4)
    # dot will be cos(pi/8)*cos(-3pi/8) + sin(pi/8)*sin(-3pi/8) = cos(pi/2) = 0...
    # Actually compute directly
    mid_sp2 = _correct_slerp(q0_sp2, q1_sp2, 0.5)
    slerp_cases.append(("shortest_path", q0_sp2, q1_sp2, 0.5, mid_sp2))

    # More negative-dot cases
    for _ in range(3):
        q_a = np.random.randn(4); q_a /= np.linalg.norm(q_a)
        if q_a[0] < 0: q_a = -q_a
        q_b = -q_a + 0.3 * np.random.randn(4)
        q_b /= np.linalg.norm(q_b)
        if q_b[0] < 0: q_b = -q_b
        if np.dot(q_a, q_b) >= 0:
            q_b = -q_b
            if q_b[0] < 0: q_b = -q_b
        mid_ab = _correct_slerp(q_a, q_b, 0.5)
        slerp_cases.append(("shortest_path", q_a, q_b, 0.5, mid_ab))

    # Normal interpolation
    for _ in range(3):
        q_a = np.random.randn(4); q_a /= np.linalg.norm(q_a)
        if q_a[0] < 0: q_a = -q_a
        q_b = np.random.randn(4); q_b /= np.linalg.norm(q_b)
        if q_b[0] < 0: q_b = -q_b
        if np.dot(q_a, q_b) < 0:
            q_b = -q_b
            if q_b[0] < 0: q_b = -q_b
        t_val = np.random.uniform(0.1, 0.9)
        mid_n = _correct_slerp(q_a, q_b, t_val)
        slerp_cases.append(("normal", q_a, q_b, t_val, mid_n))

    sid = 0
    for category, q0, q1, t, expected in slerp_cases:
        expected = standardize(expected)
        c.execute(
            "INSERT INTO test_slerp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, category,
             q0[0], q0[1], q0[2], q0[3],
             q1[0], q1[1], q1[2], q1[3],
             t,
             expected[0], expected[1], expected[2], expected[3])
        )
        sid += 1

    conn.commit()
    conn.close()
    print(f"Benchmark database created at {DB_PATH}")
    print(f"  {rid} rotation test cases")
    print(f"  {gid} geodesic test cases")
    print(f"  {sid} SLERP test cases")


if __name__ == "__main__":
    main()
