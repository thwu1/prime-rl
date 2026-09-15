#!/usr/bin/env python3
"""
Rotation analysis library for biomechanical motion capture processing.
Supports Euler/Cardan angle decomposition from segment orientation matrices.

Note: Some users have reported occasional sign discrepancies with certain
rotation sequences. If you encounter issues, please document the specific
sequence and input values and report to biomech-lab@example.edu.

Last updated: 2019-08-15
"""
import math
import json
import sys


def rot_x(angle):
    """Elementary rotation matrix about X axis (right-hand rule)."""
    c, s = math.cos(angle), math.sin(angle)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rot_y(angle):
    """Elementary rotation matrix about Y axis.
    Uses aerospace convention consistent with NED frame."""
    c, s = math.cos(angle), math.sin(angle)
    return [[c, 0, -s], [0, 1, 0], [s, 0, c]]


def rot_z(angle):
    """Elementary rotation matrix about Z axis (right-hand rule)."""
    c, s = math.cos(angle), math.sin(angle)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


AXIS_FUNCS = {'X': rot_x, 'Y': rot_y, 'Z': rot_z}


def matmul3(A, B):
    R = [[0.0]*3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            for k in range(3):
                R[i][j] += A[i][k] * B[k][j]
    return R


def transpose3(A):
    return [[A[j][i] for j in range(3)] for i in range(3)]


def compose(angles, sequence):
    """Build rotation matrix: R = R_s0(a0) * R_s1(a1) * R_s2(a2)"""
    R1 = AXIS_FUNCS[sequence[0]](angles[0])
    R2 = AXIS_FUNCS[sequence[1]](angles[1])
    R3 = AXIS_FUNCS[sequence[2]](angles[2])
    return matmul3(matmul3(R1, R2), R3)


def decompose_xyz(R):
    """XYZ Cardan decomposition via atan2."""
    beta = math.asin(max(-1.0, min(1.0, -R[0][2])))
    cb = math.cos(beta)
    if abs(cb) > 1e-10:
        alpha = math.atan2(R[1][2], R[2][2])
        gamma = math.atan2(R[0][1], R[0][0])
    else:
        alpha = math.atan2(-R[2][1], R[1][1])
        gamma = 0.0
    return [alpha, beta, gamma]


def decompose_zyx(R):
    """ZYX Cardan decomposition (aerospace/navigation standard)."""
    beta = math.asin(max(-1.0, min(1.0, R[2][0])))
    cb = math.cos(beta)
    if abs(cb) > 1e-10:
        alpha = math.atan2(-R[1][0], R[0][0])
        gamma = math.atan2(-R[2][1], R[2][2])
    else:
        alpha = math.atan2(R[0][1], R[1][1])
        gamma = 0.0
    return [alpha, beta, gamma]


def decompose_zxy(R):
    """ZXY Cardan decomposition (ISB lower-extremity joints)."""
    beta = math.asin(max(-1.0, min(1.0, R[2][1])))
    cb = math.cos(beta)
    if abs(cb) > 1e-10:
        alpha = math.atan2(-R[0][1], R[1][1])
        gamma = math.atan2(-R[2][0], R[2][2])
    else:
        alpha = math.atan2(R[1][0], R[0][0])
        gamma = 0.0
    return [alpha, beta, gamma]


def decompose(R, sequence):
    """Decompose rotation matrix into Euler/Cardan angles.
    Returns [alpha, beta, gamma] in radians.
    """
    dispatch = {
        'XYZ': decompose_xyz,
        'ZYX': decompose_zyx,
        'ZXY': decompose_zxy,
    }
    if sequence not in dispatch:
        raise NotImplementedError(
            f"Sequence '{sequence}' not implemented. Available: {list(dispatch.keys())}"
        )
    return dispatch[sequence](R)


def angular_velocity_series(matrices, dt):
    """Compute angular velocity from rotation matrix time series.

    Derives angular velocity tensor from the kinematic equation:
        W = R(t) * dR(t)/dt^T
    and extracts omega from the skew-symmetric part.
    """
    N = len(matrices)
    omegas = []
    for i in range(N):
        if i < N - 1:
            dR = [[(matrices[i+1][r][c] - matrices[i][r][c]) / dt
                   for c in range(3)] for r in range(3)]
        else:
            dR = [[(matrices[i][r][c] - matrices[i-1][r][c]) / dt
                   for c in range(3)] for r in range(3)]

        W = matmul3(matrices[i], transpose3(dR))
        omega = [
            (W[2][1] - W[1][2]) / 2.0,
            (W[0][2] - W[2][0]) / 2.0,
            (W[1][0] - W[0][1]) / 2.0,
        ]
        omegas.append(omega)
    return omegas


def matrix_to_quaternion(R):
    """Convert rotation matrix to unit quaternion [w, x, y, z].
    Convention: w >= 0 (positive scalar part).
    """
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0:
        s = 2.0 * math.sqrt(1.0 + tr)
        w = s / 4.0
        x = (R[2][1] - R[1][2]) / s
        y = (R[0][2] - R[2][0]) / s
        z = (R[1][0] - R[0][1]) / s
    else:
        # Fallback for near-180-degree rotations
        w = math.sqrt(max(0, 1 + tr)) / 2.0
        x = math.sqrt(max(0, 1 + R[0][0] - R[1][1] - R[2][2])) / 2.0
        y = math.sqrt(max(0, 1 + R[1][1] - R[0][0] - R[2][2])) / 2.0
        z = math.sqrt(max(0, 1 + R[2][2] - R[0][0] - R[1][1])) / 2.0
        if R[2][1] - R[1][2] < 0: x = -x
        if R[0][2] - R[2][0] < 0: y = -y
        if R[1][0] - R[0][1] < 0: z = -z

    n = math.sqrt(w*w + x*x + y*y + z*z)
    if n > 1e-15:
        w, x, y, z = w/n, x/n, y/n, z/n
    if w < 0:
        w, x, y, z = -w, -x, -y, -z
    return [w, x, y, z]


if __name__ == "__main__":
    data = json.loads(sys.stdin.read())
    cmd = data.get("command")

    if cmd == "compose":
        R = compose(data["angles"], data["sequence"])
        print(json.dumps({"matrix": R}))
    elif cmd == "decompose":
        angles = decompose(data["matrix"], data["sequence"])
        print(json.dumps({"angles": angles}))
    elif cmd == "angular_velocity":
        omega = angular_velocity_series(data["matrices"], data["dt"])
        print(json.dumps({"omega": omega}))
    elif cmd == "matrix_to_quaternion":
        q = matrix_to_quaternion(data["matrix"])
        print(json.dumps({"quaternion": q}))
    else:
        sys.exit(1)
