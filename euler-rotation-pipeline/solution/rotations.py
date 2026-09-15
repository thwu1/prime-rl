#!/usr/bin/env python3
"""
Rotation analysis CLI — loads /app/librotcore.so for core operations.

"""
import json
import sys
import ctypes
import math
import os
import sqlite3

# ---------------------------------------------------------------------------
# Load C library
# ---------------------------------------------------------------------------
_lib = ctypes.CDLL('/app/librotcore.so')

_lib.rotcore_compose.argtypes = [
    ctypes.POINTER(ctypes.c_double), ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_double),
]
_lib.rotcore_compose.restype = None

_lib.rotcore_decompose.argtypes = [
    ctypes.POINTER(ctypes.c_double), ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_double),
]
_lib.rotcore_decompose.restype = ctypes.c_int

_lib.rotcore_mat_to_quat.argtypes = [
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
]
_lib.rotcore_mat_to_quat.restype = None

# ---------------------------------------------------------------------------
# Wrappers around C functions
# ---------------------------------------------------------------------------

def compose(angles, sequence):
    a = (ctypes.c_double * 3)(*angles)
    R_out = (ctypes.c_double * 9)()
    _lib.rotcore_compose(a, sequence.encode(), R_out)
    return [[R_out[i * 3 + j] for j in range(3)] for i in range(3)]


def decompose(matrix, sequence):
    R_flat = (ctypes.c_double * 9)()
    for i in range(3):
        for j in range(3):
            R_flat[i * 3 + j] = matrix[i][j]
    angles = (ctypes.c_double * 3)()
    _lib.rotcore_decompose(R_flat, sequence.encode(), angles)
    return list(angles)


def mat_to_quat(matrix):
    R_flat = (ctypes.c_double * 9)()
    for i in range(3):
        for j in range(3):
            R_flat[i * 3 + j] = matrix[i][j]
    q = (ctypes.c_double * 4)()
    _lib.rotcore_mat_to_quat(R_flat, q)
    return list(q)


# ---------------------------------------------------------------------------
# Pure-Python helpers (representations that don't need C)
# ---------------------------------------------------------------------------

def quat_to_matrix(q):
    w, x, y, z = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def helical_to_matrix(h):
    angle = math.sqrt(sum(v * v for v in h))
    if angle < 1e-15:
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    ax = [v / angle for v in h]
    c, s = math.cos(angle), math.sin(angle)
    t = 1 - c
    x, y, z = ax
    return [
        [t * x * x + c,     t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c,     t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ]


def matrix_to_helical(R):
    q = mat_to_quat(R)
    w, x, y, z = q
    sin_half = math.sqrt(x * x + y * y + z * z)
    if sin_half < 1e-15:
        return [0.0, 0.0, 0.0]
    angle = 2 * math.atan2(sin_half, w)
    ax = [x / sin_half, y / sin_half, z / sin_half]
    return [ax[0] * angle, ax[1] * angle, ax[2] * angle]


def matmul3(A, B):
    R = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            for k in range(3):
                R[i][j] += A[i][k] * B[k][j]
    return R


def transpose3(A):
    return [[A[j][i] for j in range(3)] for i in range(3)]


# ---------------------------------------------------------------------------
# Continuous angle extraction
# ---------------------------------------------------------------------------

CARDAN_SEQS = {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}


def _continuity_correct(prev, curr, is_cardan):
    result = list(curr)

    if is_cardan:
        for idx in (0, 2):
            while result[idx] - prev[idx] > math.pi:
                result[idx] -= 2 * math.pi
            while result[idx] - prev[idx] < -math.pi:
                result[idx] += 2 * math.pi

        # Alternate Cardan solution: (a+pi, pi-b, g+pi)
        alt = [result[0] + math.pi, math.pi - result[1], result[2] + math.pi]
        for idx in (0, 2):
            while alt[idx] - prev[idx] > math.pi:
                alt[idx] -= 2 * math.pi
            while alt[idx] - prev[idx] < -math.pi:
                alt[idx] += 2 * math.pi

        curr_dist = sum((result[i] - prev[i]) ** 2 for i in range(3))
        alt_dist = sum((alt[i] - prev[i]) ** 2 for i in range(3))
        if alt_dist < curr_dist:
            result = alt
    else:
        for idx in (0, 2):
            while result[idx] - prev[idx] > math.pi:
                result[idx] -= 2 * math.pi
            while result[idx] - prev[idx] < -math.pi:
                result[idx] += 2 * math.pi

        # Alternate proper-Euler solution: (a+pi, -b, g+pi)
        alt = [result[0] + math.pi, -result[1], result[2] + math.pi]
        for idx in (0, 2):
            while alt[idx] - prev[idx] > math.pi:
                alt[idx] -= 2 * math.pi
            while alt[idx] - prev[idx] < -math.pi:
                alt[idx] += 2 * math.pi

        curr_dist = sum((result[i] - prev[i]) ** 2 for i in range(3))
        alt_dist = sum((alt[i] - prev[i]) ** 2 for i in range(3))
        if alt_dist < curr_dist:
            result = alt

    return result


def continuous_angles(matrices, sequence):
    is_cardan = sequence in CARDAN_SEQS
    series = []
    gimbal_frames = []
    prev = None

    for idx, mat in enumerate(matrices):
        angles = decompose(mat, sequence)
        b = angles[1]
        if is_cardan:
            if abs(math.cos(b)) < 0.01:
                gimbal_frames.append(idx)
        else:
            if abs(math.sin(b)) < 0.01:
                gimbal_frames.append(idx)

        if prev is not None:
            angles = _continuity_correct(prev, angles, is_cardan)

        series.append(angles)
        prev = angles

    return series, gimbal_frames


# ---------------------------------------------------------------------------
# Angular velocity (world-frame)
# ---------------------------------------------------------------------------

def angular_velocity(matrices, dt):
    N = len(matrices)
    omegas = []
    for i in range(N):
        if i == 0:
            dR = [[(matrices[1][r][c] - matrices[0][r][c]) / dt
                   for c in range(3)] for r in range(3)]
        elif i == N - 1:
            dR = [[(matrices[-1][r][c] - matrices[-2][r][c]) / dt
                   for c in range(3)] for r in range(3)]
        else:
            dR = [[(matrices[i + 1][r][c] - matrices[i - 1][r][c]) / (2 * dt)
                   for c in range(3)] for r in range(3)]

        Rt = transpose3(matrices[i])
        W = matmul3(dR, Rt)

        omega = [
            (W[2][1] - W[1][2]) / 2.0,
            (W[0][2] - W[2][0]) / 2.0,
            (W[1][0] - W[0][1]) / 2.0,
        ]
        omegas.append(omega)
    return omegas


# ---------------------------------------------------------------------------
# Convert between representations
# ---------------------------------------------------------------------------

def convert_repr(from_repr, to_repr, value):
    # Extract source data and convert to matrix
    if from_repr == 'matrix':
        if isinstance(value, dict) and 'matrix' in value:
            mat = value['matrix']
        else:
            mat = value
    elif from_repr == 'quaternion':
        if isinstance(value, dict) and 'quaternion' in value:
            q = value['quaternion']
        else:
            q = value
        mat = quat_to_matrix(q)
    elif from_repr == 'helical':
        if isinstance(value, dict) and 'helical' in value:
            h = value['helical']
        else:
            h = value
        mat = helical_to_matrix(h)
    elif from_repr == 'euler':
        mat = compose(value['angles'], value['sequence'])
    else:
        raise ValueError(f"Unknown from representation: {from_repr}")

    # Target euler sequence
    target_seq = None
    if to_repr == 'euler':
        if isinstance(value, dict) and 'sequence' in value:
            target_seq = value['sequence']

    # Convert to target
    if to_repr == 'matrix':
        return mat
    elif to_repr == 'quaternion':
        return mat_to_quat(mat)
    elif to_repr == 'helical':
        return matrix_to_helical(mat)
    elif to_repr == 'euler':
        angles = decompose(mat, target_seq)
        return {"angles": list(angles), "sequence": target_seq}
    else:
        raise ValueError(f"Unknown to representation: {to_repr}")


# ---------------------------------------------------------------------------
# Batch processing + SQLite
# ---------------------------------------------------------------------------

def batch_process(trial_file, conventions_file, dt):
    with open(trial_file) as f:
        trial = json.load(f)
    with open(conventions_file) as f:
        conventions = json.load(f)

    trial_joints = set()
    for frame in trial['frames']:
        trial_joints.update(frame['joints'].keys())
    common = trial_joints & set(conventions.keys())

    result = {}
    all_angles_rows = []
    all_omega_rows = []

    for joint in sorted(common):
        seq = conventions[joint]['sequence']
        matrices = []
        for frame in trial['frames']:
            if joint in frame['joints']:
                matrices.append(frame['joints'][joint])

        if not matrices:
            continue

        angle_series, gimbal_frames = continuous_angles(matrices, seq)
        omega = angular_velocity(matrices, dt)

        is_cardan = seq in CARDAN_SEQS
        for i, angles in enumerate(angle_series):
            b = angles[1]
            gl = 0
            if is_cardan:
                if abs(math.cos(b)) < 0.01:
                    gl = 1
            else:
                if abs(math.sin(b)) < 0.01:
                    gl = 1
            all_angles_rows.append((joint, i, angles[0], angles[1], angles[2], seq, gl))

        for i, om in enumerate(omega):
            all_omega_rows.append((joint, i, om[0], om[1], om[2]))

        result[joint] = {
            "sequence": seq,
            "angles": angle_series,
            "angular_velocity": omega,
            "gimbal_lock_frames": gimbal_frames,
        }

    # Write SQLite database
    db_path = '/app/results.db'
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE joint_angles (
        joint TEXT,
        frame INTEGER,
        a0 REAL,
        a1 REAL,
        a2 REAL,
        sequence TEXT,
        gimbal_locked INTEGER,
        PRIMARY KEY (joint, frame)
    )''')
    cur.execute('''CREATE TABLE angular_velocity (
        joint TEXT,
        frame INTEGER,
        wx REAL,
        wy REAL,
        wz REAL,
        PRIMARY KEY (joint, frame)
    )''')
    cur.executemany('INSERT INTO joint_angles VALUES (?,?,?,?,?,?,?)', all_angles_rows)
    cur.executemany('INSERT INTO angular_velocity VALUES (?,?,?,?,?)', all_omega_rows)
    conn.commit()
    conn.close()

    return {"joints": result}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    data = json.loads(sys.stdin.read())
    cmd = data.get('command')

    if cmd == 'compose':
        R = compose(data['angles'], data['sequence'])
        print(json.dumps({"matrix": R}))
    elif cmd == 'decompose':
        angles = decompose(data['matrix'], data['sequence'])
        print(json.dumps({"angles": angles}))
    elif cmd == 'continuous':
        series, gimbal = continuous_angles(data['matrices'], data['sequence'])
        print(json.dumps({"angle_series": series, "gimbal_lock_frames": gimbal}))
    elif cmd == 'angular_velocity':
        omega = angular_velocity(data['matrices'], data['dt'])
        print(json.dumps({"omega": omega}))
    elif cmd == 'convert':
        result = convert_repr(data['from'], data['to'], data['value'])
        print(json.dumps({"value": result}))
    elif cmd == 'batch':
        result = batch_process(data['trial_file'], data['conventions_file'], data['dt'])
        print(json.dumps(result))
    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
