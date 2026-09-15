"""
Fix four 3D geometry convention bugs in the multi-view pipeline.

Bug 1 (rotation_utils.py): mat_to_quat stores the quaternion in WXYZ order
       [r, i, j, k] instead of the documented XYZW order [i, j, k, r].

Bug 2 (geometry_utils.py): depth_to_cam_coords_points divides the x-coordinate
       by the vertical focal length fv and the y-coordinate by the horizontal
       focal length fu — these are swapped.

Bug 3 (geometry_utils.py): closed_form_inverse_se3 computes R^T @ t instead
       of -R^T @ t for the translation component of the inverse.

Bug 4 (pose_encoding.py): extri_intri_to_pose_encoding uses intrinsics[:,0,0]
       (fx) when computing vertical FoV and intrinsics[:,1,1] (fy) when computing
       horizontal FoV — these are swapped.
"""

import re


def fix_rotation_utils():
    """Fix quaternion output order from [r,i,j,k] to [i,j,k,r]."""
    with open("/app/rotation_utils.py", "r") as f:
        content = f.read()

    content = content.replace(
        "result[idx] = [r, i, j, k]",
        "result[idx] = [i, j, k, r]",
    )

    with open("/app/rotation_utils.py", "w") as f:
        f.write(content)
    print("[Fixed] rotation_utils.py: quaternion order [r,i,j,k] -> [i,j,k,r]")


def fix_geometry_utils():
    """Fix swapped focal lengths in depth unprojection and missing sign in SE3 inverse."""
    with open("/app/geometry_utils.py", "r") as f:
        content = f.read()

    # Fix swapped focal lengths: x should use fu, y should use fv
    content = content.replace(
        "x_cam = (u - cu) * depth_map / fv",
        "x_cam = (u - cu) * depth_map / fu",
    )
    content = content.replace(
        "y_cam = (v - cv) * depth_map / fu",
        "y_cam = (v - cv) * depth_map / fv",
    )

    # Fix missing negative sign in SE3 inverse translation
    content = content.replace(
        "top_right = np.matmul(R_transposed, T)",
        "top_right = -np.matmul(R_transposed, T)",
    )

    with open("/app/geometry_utils.py", "w") as f:
        f.write(content)
    print("[Fixed] geometry_utils.py: focal length swap in unprojection")
    print("[Fixed] geometry_utils.py: missing negative sign in SE3 inverse")


def fix_pose_encoding():
    """Fix swapped fx/fy in field-of-view computation."""
    with open("/app/pose_encoding.py", "r") as f:
        content = f.read()

    # fov_h should use fy (intrinsics[:,1,1]), not fx (intrinsics[:,0,0])
    content = content.replace(
        "fov_h = 2 * np.arctan((H / 2) / intrinsics[:, 0, 0])",
        "fov_h = 2 * np.arctan((H / 2) / intrinsics[:, 1, 1])",
    )
    # fov_w should use fx (intrinsics[:,0,0]), not fy (intrinsics[:,1,1])
    content = content.replace(
        "fov_w = 2 * np.arctan((W / 2) / intrinsics[:, 1, 1])",
        "fov_w = 2 * np.arctan((W / 2) / intrinsics[:, 0, 0])",
    )

    with open("/app/pose_encoding.py", "w") as f:
        f.write(content)
    print("[Fixed] pose_encoding.py: swapped fx/fy in FoV computation")


if __name__ == "__main__":
    fix_rotation_utils()
    fix_geometry_utils()
    fix_pose_encoding()
    print("\nAll four bugs fixed.")
