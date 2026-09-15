"""
Fix all mathematical bugs in the rotation conversion library.

This script reads the buggy /app/rotation_lib.py, applies targeted
corrections for each identified bug, and verifies the fixes.

Bugs fixed:
1. quaternion_to_matrix: R[0,2] sign error (xz - yw -> xz + yw)
2. matrix_to_quaternion: incomplete Shepperd method (x-only fallback)
3. axis_angle_to_matrix: Rodrigues coefficient (1+cos -> 1-cos)
4. matrix_to_euler_angles: central angle sign multiplier swapped
5. geodesic_distance: trace formula (trace+1 -> trace-1)
6. slerp: missing shortest-path quaternion negation
"""

import numpy as np

# Read the buggy source
with open('/app/rotation_lib.py', 'r') as f:
    source = f.read()

# ================================================================
# Fix 1: quaternion_to_matrix - R[0,2] element sign
# The element should be 2*(xz + yw), not 2*(xz - yw)
# ================================================================
# The first occurrence of "2*(x*z - y*w)" is R[0,2] (the bug).
# The second occurrence is R[2,0] which is correct.
# We replace only the first occurrence.
first_occurrence = source.index('2*(x*z - y*w)')
source = (source[:first_occurrence] +
          '2*(x*z + y*w)' +
          source[first_occurrence + len('2*(x*z - y*w)'):])

# ================================================================
# Fix 2: matrix_to_quaternion - implement full Shepperd method
# The buggy version always uses x-based extraction for negative trace.
# The correct version selects based on the largest diagonal element.
# ================================================================
old_else_block = """    else:
        # For negative trace, use the largest diagonal element
        # to avoid numerical instability
        val = max(0.0, 1.0 + m00 - m11 - m22)
        s = 2.0 * np.sqrt(val)
        if s > 1e-8:
            w = (m21 - m12) / s
            x = 0.25 * s
            y = (m01 + m10) / s
            z = (m02 + m20) / s
        else:
            w, x, y, z = 1.0, 0.0, 0.0, 0.0"""

new_else_block = """    elif m00 > m11 and m00 > m22:
        # x-based extraction (m00 is largest diagonal)
        s = 2.0 * np.sqrt(1.0 + m00 - m11 - m22)
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        # y-based extraction (m11 is largest diagonal)
        s = 2.0 * np.sqrt(1.0 + m11 - m00 - m22)
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        # z-based extraction (m22 is largest diagonal)
        s = 2.0 * np.sqrt(1.0 + m22 - m00 - m11)
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s"""

source = source.replace(old_else_block, new_else_block)

# ================================================================
# Fix 3: axis_angle_to_matrix - Rodrigues formula coefficient
# Should be (1 - cos(theta)), not (1 + cos(theta))
# ================================================================
source = source.replace(
    '(1 + np.cos(angle)) * (K @ K)',
    '(1 - np.cos(angle)) * (K @ K)'
)

# ================================================================
# Fix 4: matrix_to_euler_angles - central angle sign multiplier
# The condition signs are swapped. Correct:
#   -1.0 if i0 - i2 in [-1, 2] else 1.0
# Buggy:
#   1.0 if i0 - i2 in [-1, 2] else -1.0
# ================================================================
source = source.replace(
    '* (1.0 if i0 - i2 in [-1, 2] else -1.0)',
    '* (-1.0 if i0 - i2 in [-1, 2] else 1.0)'
)

# ================================================================
# Fix 5: geodesic_distance - trace formula
# Should be (trace - 1) / 2, not (trace + 1) / 2
# ================================================================
source = source.replace(
    '(np.trace(R_rel) + 1)',
    '(np.trace(R_rel) - 1)'
)

# ================================================================
# Fix 6: slerp - add shortest-path check
# When dot(q0, q1) < 0, negate q1 to interpolate the short arc
# ================================================================
old_slerp_dot = """    dot = np.clip(np.dot(q0, q1), -1.0, 1.0)

    theta = np.arccos(dot)"""

new_slerp_dot = """    dot = np.dot(q0, q1)
    if dot < 0:
        q1 = -q1
        dot = -dot
    dot = np.clip(dot, -1.0, 1.0)

    theta = np.arccos(dot)"""

source = source.replace(old_slerp_dot, new_slerp_dot)

# Write the corrected source
with open('/app/rotation_lib.py', 'w') as f:
    f.write(source)

# ================================================================
# Verify all fixes
# ================================================================
import importlib
import sys

if '/app' not in sys.path:
    sys.path.insert(0, '/app')

# Force reimport of the corrected module
if 'rotation_lib' in sys.modules:
    del sys.modules['rotation_lib']

from rotation_lib import (
    quaternion_to_matrix, matrix_to_quaternion,
    axis_angle_to_matrix, matrix_to_euler_angles,
    euler_angles_to_matrix, geodesic_distance, slerp,
    standardize_quaternion
)

# Verify Fix 1: quaternion_to_matrix
q = np.array([0.5, 0.5, 0.5, 0.5])
R = quaternion_to_matrix(q)
expected = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], dtype=float)
assert np.allclose(R, expected, atol=1e-10), f"Fix 1 FAILED: {R}"
print("Fix 1 verified: quaternion_to_matrix R[0,2] sign corrected")

# Verify Fix 2: matrix_to_quaternion for 180-deg around Y
R_180y = np.diag([-1.0, 1.0, -1.0])
q_180y = matrix_to_quaternion(R_180y)
assert np.isclose(abs(q_180y[2]), 1.0, atol=1e-6), f"Fix 2 FAILED: {q_180y}"
print("Fix 2 verified: matrix_to_quaternion Shepperd method corrected")

# Verify Fix 3: axis_angle_to_matrix Rodrigues formula
aa = np.array([0.0, np.pi, 0.0])
R_aa = axis_angle_to_matrix(aa)
expected_aa = np.diag([-1.0, 1.0, -1.0])
assert np.allclose(R_aa, expected_aa, atol=1e-10), f"Fix 3 FAILED: {R_aa}"
print("Fix 3 verified: axis_angle_to_matrix Rodrigues coefficient corrected")

# Verify Fix 4: matrix_to_euler_angles sign
angles = np.array([0.3, 0.5, 0.7])
R_euler = euler_angles_to_matrix(angles, "XYZ")
recovered = matrix_to_euler_angles(R_euler, "XYZ")
assert np.allclose(recovered, angles, atol=1e-10), f"Fix 4 FAILED: {recovered}"
print("Fix 4 verified: matrix_to_euler_angles central angle sign corrected")

# Verify Fix 5: geodesic_distance
R1 = np.eye(3)
R2 = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
dist = geodesic_distance(R1, R2)
assert np.isclose(dist, np.pi / 2, atol=1e-10), f"Fix 5 FAILED: {dist}"
print("Fix 5 verified: geodesic_distance trace formula corrected")

# Verify Fix 6: slerp shortest path
q0 = np.array([0.5, 0.5, 0.5, 0.5])
q1 = np.array([0.5, -0.5, -0.5, -0.5])
mid = slerp(q0, q1, 0.5)
mid = standardize_quaternion(mid / np.linalg.norm(mid))
identity = np.array([1.0, 0.0, 0.0, 0.0])
assert not np.allclose(mid, identity, atol=0.1), f"Fix 6 FAILED: {mid}"
print("Fix 6 verified: slerp shortest-path check added")

print("\nAll 6 fixes verified successfully!")
