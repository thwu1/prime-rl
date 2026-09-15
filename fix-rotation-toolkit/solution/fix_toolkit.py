#!/usr/bin/env python3
"""
Fix rotation_toolkit.py by:
1. Correcting three bugs in core functions
2. Evaluating candidate branch implementations via git
3. Selecting correct implementations for each stub function
4. Writing evaluation.json with selections and justifications

Bug fixes:
  1. quaternion_to_matrix  – sign error in R[1,2] and R[2,1]: (yz + xw) -> (yz - xw)
  2. axis_angle_to_matrix  – division by zero at angle=0: add safe-division guard
  3. geodesic_distance     – wrong relative rotation: R1 @ R2 -> R1.T @ R2

Candidate evaluation:
  - rotation_6d_to_matrix: alpha uses cross(b1,b2) [correct], beta uses cross(b2,b1) [det=-1]
  - slerp_rotations: alpha uses NLERP [no constant velocity], beta uses true SLERP [correct]
  - karcher_mean: alpha uses R_mean.T@R_i [correct direction], beta uses R_i.T@R_mean [diverges]
  - project_to_so3: alpha omits det correction [returns reflections], beta corrects det [correct]
"""

import json
import subprocess
import sys
import os

os.chdir('/app')

# -----------------------------------------------------------------------
# Step 1: Inspect candidate branches via git
# -----------------------------------------------------------------------
print("=== Inspecting candidate branches ===")

# Show branch listing
result = subprocess.run(['git', 'branch'], capture_output=True, text=True)
print(f"Branches:\n{result.stdout}")

# Get diff summaries for each candidate
for branch in ['candidate-alpha', 'candidate-beta']:
    result = subprocess.run(
        ['git', 'diff', 'main', branch, '--', 'rotation_toolkit.py'],
        capture_output=True, text=True,
    )
    print(f"\n=== Diff main..{branch} (first 100 lines) ===")
    lines = result.stdout.split('\n')
    print('\n'.join(lines[:100]))

# -----------------------------------------------------------------------
# Step 2: Write the fully corrected module
# -----------------------------------------------------------------------
print("\n=== Writing corrected rotation_toolkit.py ===")

CORRECTED_MODULE = '''\
"""
3D Rotation Toolkit
===================
A library for working with 3D rotation representations.

All functions operate on numpy arrays.
Quaternion convention: (w, x, y, z) with w as the scalar/real part.
"""

import numpy as np


def quaternion_to_matrix(q):
    """Convert unit quaternion(s) to rotation matrix/matrices.

    Args:
        q: array of shape (4,) or (N, 4), real part first.
    Returns:
        Rotation matrix of shape (3, 3) or (N, 3, 3).
    """
    q = np.asarray(q, dtype=np.float64)
    single = q.ndim == 1
    if single:
        q = q[None, :]

    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]

    N = q.shape[0]
    R = np.zeros((N, 3, 3), dtype=np.float64)

    R[:, 0, 0] = 1 - 2 * (y * y + z * z)
    R[:, 0, 1] = 2 * (x * y - z * w)
    R[:, 0, 2] = 2 * (x * z + y * w)
    R[:, 1, 0] = 2 * (x * y + z * w)
    R[:, 1, 1] = 1 - 2 * (x * x + z * z)
    # FIX: sign error corrected from (yz + xw) to (yz - xw)
    R[:, 1, 2] = 2 * (y * z - x * w)
    R[:, 2, 0] = 2 * (x * z - y * w)
    # FIX: matching sign correction
    R[:, 2, 1] = 2 * (y * z + x * w)
    R[:, 2, 2] = 1 - 2 * (x * x + y * y)

    if single:
        return R[0]
    return R


def matrix_to_quaternion(M):
    """Convert rotation matrix to unit quaternion (w, x, y, z).

    Uses Shepperd's method for numerical stability.

    Args:
        M: rotation matrix of shape (3, 3) or (N, 3, 3).
    Returns:
        Quaternion of shape (4,) or (N, 4) with w >= 0.
    """
    M = np.asarray(M, dtype=np.float64)
    single = M.ndim == 2
    if single:
        M = M[None, :, :]

    N = M.shape[0]
    q = np.zeros((N, 4), dtype=np.float64)

    for i in range(N):
        m = M[i]
        trace = m[0, 0] + m[1, 1] + m[2, 2]

        if trace > 0:
            s = 0.5 / np.sqrt(trace + 1.0)
            q[i, 0] = 0.25 / s
            q[i, 1] = (m[2, 1] - m[1, 2]) * s
            q[i, 2] = (m[0, 2] - m[2, 0]) * s
            q[i, 3] = (m[1, 0] - m[0, 1]) * s
        elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
            q[i, 0] = (m[2, 1] - m[1, 2]) / s
            q[i, 1] = 0.25 * s
            q[i, 2] = (m[0, 1] + m[1, 0]) / s
            q[i, 3] = (m[0, 2] + m[2, 0]) / s
        elif m[1, 1] > m[2, 2]:
            s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
            q[i, 0] = (m[0, 2] - m[2, 0]) / s
            q[i, 1] = (m[0, 1] + m[1, 0]) / s
            q[i, 2] = 0.25 * s
            q[i, 3] = (m[1, 2] + m[2, 1]) / s
        else:
            s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
            q[i, 0] = (m[1, 0] - m[0, 1]) / s
            q[i, 1] = (m[0, 2] + m[2, 0]) / s
            q[i, 2] = (m[1, 2] + m[2, 1]) / s
            q[i, 3] = 0.25 * s

        if q[i, 0] < 0:
            q[i] = -q[i]

    if single:
        return q[0]
    return q


def axis_angle_to_matrix(aa):
    """Convert axis-angle representation to rotation matrix.

    Uses the Rodrigues rotation formula with safe handling of angle=0.

    Args:
        aa: axis-angle vector of shape (3,) or (N, 3).
    Returns:
        Rotation matrix of shape (3, 3) or (N, 3, 3).
    """
    aa = np.asarray(aa, dtype=np.float64)
    single = aa.ndim == 1
    if single:
        aa = aa[None, :]

    N = aa.shape[0]
    angles = np.linalg.norm(aa, axis=-1, keepdims=True)

    # FIX: safe division to handle angle=0 without NaN
    safe_angles = np.where(angles > 1e-10, angles, np.ones_like(angles))
    axes = aa / safe_angles

    K = np.zeros((N, 3, 3), dtype=np.float64)
    K[:, 0, 1] = -axes[:, 2]
    K[:, 0, 2] = axes[:, 1]
    K[:, 1, 0] = axes[:, 2]
    K[:, 1, 2] = -axes[:, 0]
    K[:, 2, 0] = -axes[:, 1]
    K[:, 2, 1] = axes[:, 0]

    angles_3d = angles[:, :, None]
    I = np.eye(3)[None, :, :]

    R = I + np.sin(angles_3d) * K + (1 - np.cos(angles_3d)) * (K @ K)

    if single:
        return R[0]
    return R


def matrix_to_axis_angle(M):
    """Convert rotation matrix to axis-angle representation.

    Args:
        M: rotation matrix of shape (3, 3).
    Returns:
        Axis-angle vector of shape (3,).
    """
    M = np.asarray(M, dtype=np.float64)

    trace = M[0, 0] + M[1, 1] + M[2, 2]
    cos_angle = np.clip((trace - 1) / 2, -1.0, 1.0)
    angle = np.arccos(cos_angle)

    if angle < 1e-10:
        return np.zeros(3, dtype=np.float64)

    if np.abs(angle - np.pi) < 1e-6:
        RpI = M + np.eye(3)
        col_norms = np.linalg.norm(RpI, axis=0)
        best_col = np.argmax(col_norms)
        axis = RpI[:, best_col]
        axis = axis / np.linalg.norm(axis)
        return angle * axis

    axis = np.array([
        M[2, 1] - M[1, 2],
        M[0, 2] - M[2, 0],
        M[1, 0] - M[0, 1],
    ])
    axis = axis / (2 * np.sin(angle))
    return angle * axis


def geodesic_distance(R1, R2):
    """Compute geodesic distance between two rotation matrices on SO(3).

    Args:
        R1, R2: rotation matrices of shape (3, 3).
    Returns:
        Geodesic distance in radians (scalar in [0, pi]).
    """
    R1 = np.asarray(R1, dtype=np.float64)
    R2 = np.asarray(R2, dtype=np.float64)
    # FIX: use R1.T @ R2 instead of R1 @ R2
    R_rel = R1.T @ R2
    cos_angle = np.clip((np.trace(R_rel) - 1) / 2, -1.0, 1.0)
    return np.arccos(cos_angle)


def matrix_to_rotation_6d(M):
    """Convert rotation matrix to 6D rotation representation.

    Args:
        M: rotation matrix of shape (3, 3).
    Returns:
        6D representation of shape (6,).
    """
    M = np.asarray(M, dtype=np.float64)
    return M[:2, :].flatten()


# Selected from candidate-alpha: correct Gram-Schmidt with cross(b1, b2)
def rotation_6d_to_matrix(d6):
    """Convert 6D rotation representation to rotation matrix.

    Uses Gram-Schmidt orthogonalization (Zhou et al. 2019).

    Args:
        d6: 6D representation of shape (6,).
    Returns:
        Rotation matrix of shape (3, 3).
    """
    d6 = np.asarray(d6, dtype=np.float64)
    a1, a2 = d6[:3], d6[3:]

    b1 = a1 / np.linalg.norm(a1)
    b2 = a2 - np.dot(b1, a2) * b1
    b2 = b2 / np.linalg.norm(b2)
    b3 = np.cross(b1, b2)

    return np.stack([b1, b2, b3], axis=0)


# Selected from candidate-beta: true spherical SLERP with antipodal handling
def slerp_rotations(R1, R2, t):
    """Spherical linear interpolation between two rotation matrices.

    Interpolates along the geodesic on SO(3) with constant angular velocity.

    Args:
        R1, R2: rotation matrices of shape (3, 3).
        t: interpolation parameter in [0, 1].
    Returns:
        Interpolated rotation matrix of shape (3, 3).
    """
    q1 = matrix_to_quaternion(R1)
    q2 = matrix_to_quaternion(R2)

    dot = np.dot(q1, q2)
    if dot < 0:
        q2 = -q2
        dot = -dot

    dot = np.clip(dot, 0.0, 1.0)

    if dot > 0.9995:
        q = q1 + t * (q2 - q1)
        q = q / np.linalg.norm(q)
    else:
        theta = np.arccos(dot)
        sin_theta = np.sin(theta)
        q = (np.sin((1 - t) * theta) * q1 + np.sin(t * theta) * q2) / sin_theta

    return quaternion_to_matrix(q)


# Selected from candidate-alpha: correct log-map direction (R_mean.T @ R_i)
def karcher_mean(rotations, weights=None, max_iter=100, tol=1e-10):
    """Compute the Karcher (geodesic) mean of rotation matrices.

    Args:
        rotations: array of shape (N, 3, 3).
        weights: optional array of shape (N,). Uniform if None.
        max_iter: maximum iterations.
        tol: convergence tolerance.
    Returns:
        Mean rotation matrix of shape (3, 3).
    """
    rotations = np.asarray(rotations, dtype=np.float64)
    N = rotations.shape[0]

    if weights is None:
        weights = np.ones(N, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    weights = weights / weights.sum()

    R_mean = rotations[0].copy()

    for _ in range(max_iter):
        delta = np.zeros(3, dtype=np.float64)
        for i in range(N):
            R_rel = R_mean.T @ rotations[i]
            log_rel = matrix_to_axis_angle(R_rel)
            delta += weights[i] * log_rel

        if np.linalg.norm(delta) < tol:
            break

        R_mean = R_mean @ axis_angle_to_matrix(delta)

    return R_mean


# Selected from candidate-beta: SVD with determinant correction
def project_to_so3(M):
    """Project a 3x3 matrix to the nearest rotation matrix via SVD.

    Args:
        M: arbitrary 3x3 matrix.
    Returns:
        Nearest rotation matrix with det = +1.
    """
    M = np.asarray(M, dtype=np.float64)
    U, S, Vt = np.linalg.svd(M)
    R = U @ Vt

    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt

    return R
'''

with open('/app/rotation_toolkit.py', 'w') as f:
    f.write(CORRECTED_MODULE)

print("Corrected rotation_toolkit.py written.")

# -----------------------------------------------------------------------
# Step 3: Write evaluation.json
# -----------------------------------------------------------------------
print("\n=== Writing evaluation.json ===")

evaluation = {
    "rotation_6d_to_matrix": {
        "selected": "alpha",
        "reason": "Alpha uses cross(b1, b2) which produces a right-handed frame with det=+1. Beta uses cross(b2, b1) = -cross(b1, b2), yielding det=-1 (an improper rotation/reflection)."
    },
    "slerp_rotations": {
        "selected": "beta",
        "reason": "Beta implements true spherical linear interpolation (SLERP) with arccos/sin weighting, producing constant angular velocity. Alpha uses normalized linear interpolation (NLERP), which speeds up at the midpoint and violates constant angular velocity."
    },
    "karcher_mean": {
        "selected": "alpha",
        "reason": "Alpha computes the log map as matrix_to_axis_angle(R_mean.T @ R_i), the correct tangent vector pointing from the current mean toward each sample. Beta reverses this to R_i.T @ R_mean, which points in the opposite direction and causes the iteration to diverge for N > 1."
    },
    "project_to_so3": {
        "selected": "beta",
        "reason": "Beta includes the essential determinant correction: when det(U @ Vt) = -1, it flips the last column of U to ensure a proper rotation. Alpha omits this check, returning reflections (det=-1) for some inputs like diag(1, 1, -1)."
    }
}

with open('/app/evaluation.json', 'w') as f:
    json.dump(evaluation, f, indent=2)

print("evaluation.json written.")

# -----------------------------------------------------------------------
# Step 4: Commit fixes
# -----------------------------------------------------------------------
print("\n=== Committing fixes ===")

subprocess.run(['git', 'add', 'rotation_toolkit.py', 'evaluation.json'], cwd='/app')
subprocess.run(
    ['git', 'commit', '-m',
     'Fix core bugs and integrate best candidate implementations\n\n'
     'Bug fixes: quaternion_to_matrix sign error, axis_angle_to_matrix\n'
     'zero-division, geodesic_distance wrong formula.\n\n'
     'Selected: alpha 6D + karcher, beta SLERP + project_to_so3.'],
    cwd='/app',
)

# -----------------------------------------------------------------------
# Step 5: Smoke tests
# -----------------------------------------------------------------------
print("\n=== Running smoke tests ===")

sys.path.insert(0, '/app')
if 'rotation_toolkit' in sys.modules:
    del sys.modules['rotation_toolkit']

import numpy as np
from rotation_toolkit import (
    quaternion_to_matrix, axis_angle_to_matrix, geodesic_distance,
    rotation_6d_to_matrix, matrix_to_rotation_6d,
    slerp_rotations, karcher_mean, project_to_so3,
)

# Smoke test 1: quaternion identity
R = quaternion_to_matrix(np.array([1.0, 0, 0, 0]))
assert np.allclose(R, np.eye(3)), "quaternion identity failed"

# Smoke test 2: quaternion 90-deg around x sign check
angle = np.pi / 2
q_x90 = np.array([np.cos(angle / 2), np.sin(angle / 2), 0, 0])
R_x90 = quaternion_to_matrix(q_x90)
assert np.isclose(R_x90[1, 2], -1.0, atol=1e-10), f"sign fix failed: R[1,2]={R_x90[1, 2]}"

# Smoke test 3: axis-angle zero -> identity (no NaN)
R_zero = axis_angle_to_matrix(np.array([0.0, 0.0, 0.0]))
assert np.allclose(R_zero, np.eye(3)) and np.all(np.isfinite(R_zero))

# Smoke test 4: geodesic self-distance
Rz = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=np.float64)
assert np.isclose(geodesic_distance(Rz, Rz), 0.0, atol=1e-12)

# Smoke test 5: 6D roundtrip
d6 = matrix_to_rotation_6d(Rz)
R_back = rotation_6d_to_matrix(d6)
assert np.allclose(Rz, R_back, atol=1e-10), "6D roundtrip failed"

# Smoke test 6: project_to_so3 with reflection input
R_proj = project_to_so3(np.diag([1.0, 1.0, -1.0]))
assert np.isclose(np.linalg.det(R_proj), 1.0, atol=1e-10), "det correction failed"

# Smoke test 7: slerp endpoints
R1, R2 = np.eye(3), Rz
assert np.allclose(slerp_rotations(R1, R2, 0.0), R1, atol=1e-10)
assert np.allclose(slerp_rotations(R1, R2, 1.0), R2, atol=1e-10)

# Smoke test 8: karcher mean of single rotation
assert np.allclose(karcher_mean(np.array([Rz])), Rz, atol=1e-8)

# Smoke test 9: evaluation.json exists and has correct hash
import hashlib
with open('/app/evaluation.json') as f:
    eval_data = json.load(f)
ordered = ['rotation_6d_to_matrix', 'slerp_rotations', 'karcher_mean', 'project_to_so3']
sel_str = ':'.join(eval_data[f]['selected'] for f in ordered)
digest = hashlib.sha256(sel_str.encode()).hexdigest()[:16]
assert digest == '209a91e99d2e40f3', f"evaluation hash mismatch: {digest}"

print("\nAll smoke tests passed. Rotation toolkit fixed and evaluation complete.")
