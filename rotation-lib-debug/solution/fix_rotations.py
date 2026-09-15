"""
Fix the 5 mathematical bugs in /app/rotation_lib.py.

Bug 1 (matrix_to_quaternion): Uses argmin instead of argmax to select the
    quaternion branch in Shepperd's method, picking the worst-conditioned
    component and causing numerical garbage for most rotations.

Bug 2 (euler_angles_to_matrix): Multiplies the per-axis rotation matrices
    in reversed order (matrices[2] @ matrices[1] @ matrices[0] instead of
    matrices[0] @ matrices[1] @ matrices[2]), computing extrinsic instead
    of intrinsic rotations.

Bug 3 (axis_angle_to_matrix): Uses sin(theta) instead of sinc(theta/pi) =
    sin(theta)/theta in the Rodrigues formula. Since the cross-product matrix
    K is unnormalized (K = theta * K_hat), the linear term should be
    (sin(theta)/theta) * K = sinc(theta/pi) * K, not sin(theta) * K.
    The bug makes the result non-orthogonal for all non-trivial angles.

Bug 4 (rotation_6d_to_matrix): Computes cross(b2, b1) instead of cross(b1, b2)
    in the Gram-Schmidt process, producing a left-handed frame (det = -1)
    instead of a right-handed rotation (det = +1).

Bug 5 (matrix_to_euler_angles): Uses torch.acos instead of torch.asin to
    extract the central angle for Tait-Bryan conventions. The element
    matrix[i0, i2] equals sin(central_angle) (up to sign), not
    cos(central_angle), so asin is the correct inverse.
"""


with open("/app/rotation_lib.py", "r") as f:
    code = f.read()

# Fix 1: matrix_to_quaternion - argmin -> argmax
code = code.replace(".argmin(dim=-1", ".argmax(dim=-1")

# Fix 2: euler_angles_to_matrix - correct the matrix multiplication order
code = code.replace(
    "torch.matmul(torch.matmul(matrices[2], matrices[1]), matrices[0])",
    "torch.matmul(torch.matmul(matrices[0], matrices[1]), matrices[2])",
)

# Fix 3: axis_angle_to_matrix - sin(angles) -> sinc(angles / pi)
code = code.replace(
    "+ torch.sin(angles) * cross_product_matrix",
    "+ torch.sinc(angles / torch.pi) * cross_product_matrix",
)

# Fix 4: rotation_6d_to_matrix - swap cross product argument order
code = code.replace(
    "torch.cross(b2, b1, dim=-1)",
    "torch.cross(b1, b2, dim=-1)",
)

# Fix 5: matrix_to_euler_angles - acos -> asin for Tait-Bryan central angle
# Only replace the Tait-Bryan branch (which indexes i0, i2), not the proper
# Euler branch (which indexes i0, i0)
code = code.replace(
    "central_angle = torch.acos(\n            torch.clamp(matrix[..., i0, i2]",
    "central_angle = torch.asin(\n            torch.clamp(matrix[..., i0, i2]",
)

with open("/app/rotation_lib.py", "w") as f:
    f.write(code)

print("All 5 bugs fixed in /app/rotation_lib.py")
