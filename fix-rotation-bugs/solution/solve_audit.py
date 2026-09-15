#!/usr/bin/env python3
"""Solution: analyze rotation libraries and produce all audit deliverables.

Generates:
  /app/audit_report.json   - structured bug analysis report
  /app/rotation_service.py - standalone corrected rotation library
  /app/pipeline_fixed.json - corrected pipeline routing
"""
import sqlite3
import json

DB_PATH = "/app/rotations.db"
FUNCTIONS = [
    "quaternion_to_matrix", "matrix_to_quaternion", "axis_angle_to_matrix",
    "matrix_to_euler_angles", "geodesic_distance", "slerp",
]
LIBRARIES = ["alpha", "beta", "gamma"]
THRESHOLD = 1e-6

# Detailed root cause descriptions for each flawed implementation
ROOT_CAUSES = {
    "quaternion_to_matrix": {
        "beta": (
            "Beta's quaternion_to_matrix has a sign error in the R[0,2] element: "
            "uses 2*(x*z - y*w) instead of the correct 2*(x*z + y*w). This makes "
            "R[0,2] equal to R[2,0] (both become 2*(xz-yw)), breaking the "
            "antisymmetric structure needed for proper rotation matrices. The error "
            "manifests for any quaternion where y*w is nonzero, producing matrices "
            "that are not valid elements of SO(3)."
        ),
    },
    "matrix_to_quaternion": {
        "alpha": (
            "Alpha's matrix_to_quaternion uses an incomplete Shepperd method: when "
            "trace <= 0, it only falls back to x-component extraction using "
            "1 + m00 - m11 - m22. This works when m00 is the largest diagonal "
            "element but fails for 180-degree rotations around the Y or Z axis, "
            "where m11 or m22 is largest. In those cases the discriminant becomes "
            "zero or negative, causing numerical instability or incorrect results."
        ),
        "gamma": (
            "Gamma's matrix_to_quaternion uses an incomplete Shepperd method: when "
            "trace <= 0, it only falls back to z-component extraction using "
            "1 + m22 - m00 - m11. This works when m22 is the largest diagonal "
            "element but fails for 180-degree rotations around the X or Y axis, "
            "where m00 or m11 is largest. The full method must check all four "
            "candidates (trace, m00, m11, m22) and select the largest."
        ),
    },
    "axis_angle_to_matrix": {
        "gamma": (
            "Gamma's axis_angle_to_matrix uses (1 + cos(angle)) as the coefficient "
            "for K^2 in the Rodrigues formula instead of the correct (1 - cos(angle)). "
            "The correct Rodrigues formula is R = I + sin(a)*K + (1-cos(a))*K^2. "
            "With (1+cos), the formula produces incorrect results for all non-zero "
            "angles, with maximum error at 180 degrees where cos(a)=-1 and the K^2 "
            "coefficient should be 2 but becomes 0."
        ),
    },
    "matrix_to_euler_angles": {
        "beta": (
            "Beta's matrix_to_euler_angles has a swapped sign multiplier in the "
            "central angle computation for Tait-Bryan conventions. It uses "
            "(1.0 if i0-i2 in [-1,2] else -1.0) instead of the correct "
            "(-1.0 if i0-i2 in [-1,2] else 1.0). This inverts the sign applied to "
            "the arcsin argument, producing a negated middle Euler angle which also "
            "causes the first and third angles to be computed incorrectly."
        ),
    },
    "geodesic_distance": {
        "alpha": (
            "Alpha's geodesic_distance uses (trace(R_rel) + 1) / 2 instead of the "
            "correct (trace(R_rel) - 1) / 2 in the SO(3) geodesic formula. Since "
            "trace(R) = 1 + 2*cos(angle) for a rotation by angle, the correct "
            "cosine extraction is (trace-1)/2 = cos(angle). Using +1 shifts the "
            "cosine by 1, giving cos_angle = (trace+1)/2 = cos(angle) + 1, which "
            "produces incorrect angular distances for all non-identity rotations."
        ),
    },
    "slerp": {
        "gamma": (
            "Gamma's SLERP implementation does not check for negative dot product "
            "between input quaternions. When dot(q0,q1) < 0, one quaternion should "
            "be negated to ensure interpolation follows the shortest path on the "
            "quaternion hypersphere. Without this check, SLERP traverses the long "
            "arc (> 180 degrees) instead of the short arc, producing interpolated "
            "rotations far from the expected result."
        ),
    },
}


def analyze():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    bug_analysis = {}
    optimal = {}

    for fn in FUNCTIONS:
        correct, flawed = [], []
        best_lib, best_err = None, float('inf')

        for lib in LIBRARIES:
            row = c.execute(
                "SELECT MAX(error) FROM benchmark_results "
                "WHERE library=? AND func=?",
                (lib, fn)
            ).fetchone()
            max_err = row[0] if row[0] is not None else 999.0

            if max_err < THRESHOLD:
                correct.append(lib)
                if max_err < best_err:
                    best_err = max_err
                    best_lib = lib
            else:
                flawed.append(lib)

        # Collect root causes and affected categories
        root_cause_parts = []
        all_cats = set()
        for fl in flawed:
            if fn in ROOT_CAUSES and fl in ROOT_CAUSES[fn]:
                root_cause_parts.append(ROOT_CAUSES[fn][fl])
            # Query affected categories from benchmark data
            rows = c.execute(
                "SELECT DISTINCT category FROM benchmark_results "
                "WHERE library=? AND func=? AND error >= ?",
                (fl, fn, THRESHOLD)
            ).fetchall()
            all_cats.update(r[0] for r in rows)

        bug_analysis[fn] = {
            "correct_libraries": sorted(correct),
            "flawed_libraries": sorted(flawed),
            "root_cause": " ".join(root_cause_parts) if root_cause_parts else
                f"Implementation error in {fn} exceeds threshold.",
            "affected_categories": sorted(all_cats),
        }
        optimal[fn] = best_lib or (correct[0] if correct else "alpha")

    conn.close()

    # Read original pipeline config for issue analysis
    with open("/app/pipeline.json") as f:
        pipeline = json.load(f)

    pipeline_issues = {}
    for fn in FUNCTIONS:
        current = pipeline["backends"][fn]
        correct_set = bug_analysis[fn]["correct_libraries"]
        pipeline_issues[fn] = (
            f"Currently routed to '{current}' which is flawed. "
            f"Should route to one of: {correct_set}."
        )

    propagation = {
        "matrix_to_axis_angle_dependency": (
            "matrix_to_axis_angle is computed via matrix_to_quaternion followed by "
            "quaternion_to_axis_angle. Any bug in matrix_to_quaternion (present in "
            "Alpha and Gamma) propagates to matrix_to_axis_angle, producing incorrect "
            "axis-angle representations for 180-degree and near-180-degree rotations."
        ),
        "pose_interpolation_chain": (
            "The pose_interpolation chain in pipeline.json routes "
            "matrix_to_quaternion to Alpha (flawed: incomplete Shepperd), "
            "slerp to Gamma (flawed: no shortest-path check), and "
            "quaternion_to_matrix to Beta (flawed: R[0,2] sign error). "
            "All three stages independently produce errors, and the "
            "matrix_to_quaternion error from stage 0 propagates through "
            "stages 1 and 2, compounding the total error."
        ),
        "alignment_metric_chain": (
            "The alignment_metric chain routes matrix_to_quaternion to Alpha "
            "(flawed) and geodesic_distance to Alpha (also flawed). The "
            "quaternion extraction error from stage 0 feeds into the geodesic "
            "computation which itself has the wrong trace formula, causing "
            "double-compounded errors in alignment measurements."
        ),
    }

    report = {
        "bug_analysis": bug_analysis,
        "propagation_analysis": propagation,
        "pipeline_issues": pipeline_issues,
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote /app/audit_report.json")

    # Write fixed pipeline config
    fixed_pipeline = dict(pipeline)
    fixed_pipeline["backends"] = optimal
    with open("/app/pipeline_fixed.json", "w") as f:
        json.dump(fixed_pipeline, f, indent=2)
    print("Wrote /app/pipeline_fixed.json")


def write_rotation_service():
    """Write a standalone rotation_service.py with all correct implementations."""
    code = '''\
"""Standalone corrected rotation conversion library.

All implementations are mathematically correct. This module is self-contained
and does not depend on lib_alpha, lib_beta, or lib_gamma.
"""
import numpy as np


def _index_from_letter(letter):
    if letter == "X": return 0
    if letter == "Y": return 1
    if letter == "Z": return 2
    raise ValueError(f"Invalid axis: {letter}")


def _single_axis_rotation(axis, angle):
    c, s = np.cos(angle), np.sin(angle)
    if axis == "X":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)
    if axis == "Y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)
    if axis == "Z":
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)
    raise ValueError(f"Invalid axis: {axis}")


def _angle_from_tan(axis, other_axis, data, horizontal, tait_bryan):
    i1, i2 = {"X": (2, 1), "Y": (0, 2), "Z": (1, 0)}[axis]
    if horizontal:
        i2, i1 = i1, i2
    even = (axis + other_axis) in ["XY", "YZ", "ZX"]
    if horizontal == even:
        return np.arctan2(data[i1], data[i2])
    if tait_bryan:
        return np.arctan2(-data[i2], data[i1])
    return np.arctan2(data[i2], -data[i1])


def standardize_quaternion(q):
    """Ensure quaternion has non-negative scalar component."""
    q = np.asarray(q, dtype=float).copy()
    if q[0] < 0:
        q = -q
    return q


def quaternion_to_matrix(q):
    """Convert unit quaternion (w,x,y,z) to 3x3 rotation matrix."""
    q = np.asarray(q, dtype=float)
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w),     2*(x*z + y*w)],
        [2*(x*y + z*w),     1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w),     2*(y*z + x*w),      1 - 2*(x*x + y*y)]
    ])


def matrix_to_quaternion(R):
    """Convert 3x3 rotation matrix to unit quaternion using full Shepperd method.

    Selects the largest of {trace, m00, m11, m22} to maximize numerical
    stability, handling all 180-degree rotation axes correctly.
    """
    R = np.asarray(R, dtype=float)
    m00, m01, m02 = R[0, 0], R[0, 1], R[0, 2]
    m10, m11, m12 = R[1, 0], R[1, 1], R[1, 2]
    m20, m21, m22 = R[2, 0], R[2, 1], R[2, 2]
    trace = m00 + m11 + m22
    if trace > 0:
        s = 2.0 * np.sqrt(1.0 + trace)
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = 2.0 * np.sqrt(1.0 + m00 - m11 - m22)
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = 2.0 * np.sqrt(1.0 + m11 - m00 - m22)
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = 2.0 * np.sqrt(1.0 + m22 - m00 - m11)
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    q = np.array([w, x, y, z])
    q = q / np.linalg.norm(q)
    return standardize_quaternion(q)


def axis_angle_to_quaternion(axis_angle):
    """Convert axis-angle (3D vector, direction=axis, magnitude=angle) to quaternion."""
    axis_angle = np.asarray(axis_angle, dtype=float)
    angle = np.linalg.norm(axis_angle)
    if angle < 1e-10:
        return np.array([1.0, 0.0, 0.0, 0.0])
    half = angle / 2.0
    axis = axis_angle / angle
    return np.array([np.cos(half), *(np.sin(half) * axis)])


def quaternion_to_axis_angle(q):
    """Convert unit quaternion to axis-angle representation."""
    q = np.asarray(q, dtype=float)
    q = q / np.linalg.norm(q)
    q = standardize_quaternion(q)
    w, xyz = q[0], q[1:]
    sin_half = np.linalg.norm(xyz)
    if sin_half < 1e-10:
        return np.zeros(3)
    angle = 2.0 * np.arctan2(sin_half, w)
    return angle * (xyz / sin_half)


def axis_angle_to_matrix(axis_angle):
    """Convert axis-angle to rotation matrix using Rodrigues formula.

    R = I + sin(a)*K + (1 - cos(a))*K^2
    where K is the skew-symmetric matrix of the unit rotation axis.
    """
    axis_angle = np.asarray(axis_angle, dtype=float)
    angle = np.linalg.norm(axis_angle)
    if angle < 1e-10:
        return np.eye(3)
    axis = axis_angle / angle
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0]
    ])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def matrix_to_axis_angle(R):
    """Convert rotation matrix to axis-angle via quaternion intermediate."""
    return quaternion_to_axis_angle(matrix_to_quaternion(R))


def euler_angles_to_matrix(angles, convention):
    """Convert Euler angles to rotation matrix.

    Args:
        angles: array of 3 angles in radians
        convention: 3-letter string like "XYZ", "ZYX", etc.
    """
    angles = np.asarray(angles, dtype=float)
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    if convention[1] in (convention[0], convention[2]):
        raise ValueError(f"Invalid convention {convention}.")
    matrices = [_single_axis_rotation(c, a) for c, a in zip(convention, angles)]
    return matrices[0] @ matrices[1] @ matrices[2]


def matrix_to_euler_angles(R, convention):
    """Convert rotation matrix to Euler angles.

    Uses the correct sign convention for Tait-Bryan decompositions:
    multiplier = -1.0 when (i0 - i2) is in {-1, 2}, else 1.0.
    """
    R = np.asarray(R, dtype=float)
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    if convention[1] in (convention[0], convention[2]):
        raise ValueError(f"Invalid convention {convention}.")
    i0 = _index_from_letter(convention[0])
    i2 = _index_from_letter(convention[2])
    tait_bryan = i0 != i2
    if tait_bryan:
        central_angle = np.arcsin(
            np.clip(R[i0, i2], -1.0, 1.0)
            * (-1.0 if i0 - i2 in [-1, 2] else 1.0)
        )
    else:
        central_angle = np.arccos(np.clip(R[i0, i0], -1.0, 1.0))
    o = (
        _angle_from_tan(convention[0], convention[1], R[:, i2], False, tait_bryan),
        central_angle,
        _angle_from_tan(convention[2], convention[1], R[i0, :], True, tait_bryan),
    )
    return np.array(o)


def rotation_6d_to_matrix(d6):
    """Convert 6D rotation representation to matrix via Gram-Schmidt."""
    d6 = np.asarray(d6, dtype=float)
    a1, a2 = d6[:3], d6[3:]
    b1 = a1 / np.linalg.norm(a1)
    b2 = a2 - np.dot(b1, a2) * b1
    b2 = b2 / np.linalg.norm(b2)
    return np.stack([b1, b2, np.cross(b1, b2)], axis=0)


def matrix_to_rotation_6d(R):
    """Convert rotation matrix to 6D representation (first two rows)."""
    return np.asarray(R, dtype=float)[:2, :].flatten().copy()


def geodesic_distance(R1, R2):
    """Compute geodesic distance on SO(3) between two rotation matrices.

    Uses the correct formula: angle = arccos((trace(R1 @ R2^T) - 1) / 2).
    Since trace(R) = 1 + 2*cos(angle), we have cos(angle) = (trace - 1) / 2.
    """
    R1 = np.asarray(R1, dtype=float)
    R2 = np.asarray(R2, dtype=float)
    R_rel = R1 @ R2.T
    cos_angle = np.clip((np.trace(R_rel) - 1) / 2.0, -1.0, 1.0)
    return float(np.arccos(cos_angle))


def slerp(q0, q1, t):
    """Spherical linear interpolation with shortest-path guarantee.

    If dot(q0, q1) < 0, negates q1 to ensure interpolation follows
    the shorter arc on the quaternion hypersphere.
    """
    q0 = np.asarray(q0, dtype=float)
    q1 = np.asarray(q1, dtype=float)
    q0 = q0 / np.linalg.norm(q0)
    q1 = q1 / np.linalg.norm(q1)
    dot = np.dot(q0, q1)
    if dot < 0:
        q1 = -q1
        dot = -dot
    dot = np.clip(dot, -1.0, 1.0)
    theta = np.arccos(dot)
    if abs(theta) < 1e-10:
        return q0.copy()
    sin_theta = np.sin(theta)
    w0 = np.sin((1.0 - t) * theta) / sin_theta
    w1 = np.sin(t * theta) / sin_theta
    result = w0 * q0 + w1 * q1
    return result / np.linalg.norm(result)


def random_rotation_matrix():
    """Generate a uniformly random rotation matrix via QR decomposition."""
    H = np.random.randn(3, 3)
    Q, R = np.linalg.qr(H)
    Q = Q @ np.diag(np.sign(np.diag(R)))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q
'''
    with open("/app/rotation_service.py", "w") as f:
        f.write(code)
    print("Wrote /app/rotation_service.py")


if __name__ == "__main__":
    analyze()
    write_rotation_service()
