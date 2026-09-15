"""
API Specification for /app/lie_ik.py
=====================================

This module provides Lie group operations on SO(3) and SE(3),
and a QP-based differential IK solver with collision avoidance.

Tangent-space conventions
-------------------------
  SO3 tangent: omega = (omega_x, omega_y, omega_z) in R^3
  SE3 tangent (twist): xi = (v_x, v_y, v_z, omega_x, omega_y, omega_z) in R^6
      First 3 components: linear velocity.
      Last  3 components: angular velocity.

Homogeneous-matrix convention
-----------------------------
  T = [[R, t],   in R^{4x4},   R in SO(3),  t in R^3
       [0, 1]]
"""

import numpy as np
import mujoco
from typing import Tuple, List


# =====================================================================
# SO(3): Special Orthogonal Group  (3-D rotations)
# =====================================================================

def so3_skew(v: np.ndarray) -> np.ndarray:
    """3-D vector  ->  3x3 skew-symmetric matrix.

    Property:  skew(v) @ w  ==  cross(v, w)   for all w in R^3.

    Args:   v  (3,)
    Returns: (3, 3) skew-symmetric matrix.
    """
    ...


def so3_exp(omega: np.ndarray) -> np.ndarray:
    """Exponential map  so(3) -> SO(3).

    Must produce orthogonal matrices with determinant 1.
    Numerically stable for ||omega|| -> 0.

    Args:   omega  (3,)
    Returns: R  (3, 3)  rotation matrix.
    """
    ...


def so3_log(R: np.ndarray) -> np.ndarray:
    """Logarithmic map  SO(3) -> so(3).  Inverse of so3_exp.

    Must handle rotation angles near 0 and near pi.

    Args:   R  (3, 3)
    Returns: omega  (3,).
    """
    ...


def so3_left_jacobian(omega: np.ndarray) -> np.ndarray:
    """Left Jacobian of SO(3).

    so3_left_jacobian(zeros(3)) = I_3.

    Args:   omega  (3,)
    Returns: (3, 3).
    """
    ...


def so3_left_jacobian_inv(omega: np.ndarray) -> np.ndarray:
    """Analytical inverse of the SO(3) left Jacobian.

    so3_left_jacobian(omega) @ so3_left_jacobian_inv(omega) = I_3.

    Args:   omega  (3,)
    Returns: (3, 3).
    """
    ...


# =====================================================================
# SE(3): Special Euclidean Group  (rigid-body transforms)
# =====================================================================

def se3_exp(twist: np.ndarray) -> np.ndarray:
    """Exponential map  se(3) -> SE(3).

    Maps a twist vector to a homogeneous transformation matrix.
    se3_exp(zeros(6)) = I_4.

    Args:   twist  (6,)
    Returns: T  (4, 4)  homogeneous transformation matrix.
    """
    ...


def se3_log(T: np.ndarray) -> np.ndarray:
    """Logarithmic map  SE(3) -> se(3).  Inverse of se3_exp.

    Args:   T  (4, 4)
    Returns: twist  (6,)  with  twist[:3] = v,  twist[3:] = omega.
    """
    ...


def se3_adjoint(T: np.ndarray) -> np.ndarray:
    """Adjoint representation of SE(3).

    Transforms twists between coordinate frames:
        xi_a = Ad(T_ab) @ xi_b

    Properties:
        Ad(I) = I_6
        Ad(T1 @ T2) = Ad(T1) @ Ad(T2)

    Has 2x2 block structure derived from rotation and
    translation components of T.

    Args:   T  (4, 4)
    Returns: (6, 6).
    """
    ...


def se3_left_jacobian(twist: np.ndarray) -> np.ndarray:
    """Left Jacobian of SE(3)  (6x6).

    se3_left_jacobian(zeros(6)) = I_6.

    Has 2x2 block structure with SO(3) left Jacobians
    on the diagonal and a coupling block.

    Args:   twist  (6,)
    Returns: (6, 6).
    """
    ...


def se3_left_jacobian_inv(twist: np.ndarray) -> np.ndarray:
    """Analytical inverse of the SE(3) left Jacobian  (6x6).

    se3_left_jacobian(twist) @ se3_left_jacobian_inv(twist) = I_6.

    Args:   twist  (6,)
    Returns: (6, 6).
    """
    ...


# =====================================================================
# Inverse Kinematics
# =====================================================================

def compute_frame_error(
    T_current: np.ndarray,
    T_target: np.ndarray,
) -> np.ndarray:
    """6-D twist error between current and target frames in body frame.

    Zero when T_current == T_target.
    First 3 components: translational error.
    Last  3 components: rotational error.

    Args:
        T_current: (4, 4) current end-effector pose.
        T_target:  (4, 4) desired end-effector pose.
    Returns: (6,) twist error.
    """
    ...


def compute_body_jacobian(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    site_id: int,
) -> np.ndarray:
    """Body-frame Jacobian for a MuJoCo site.

    Relates joint velocities to body-frame spatial velocity.
    Consistent with MuJoCo's world-frame Jacobian via adjoint:
        Ad(T_ws) @ J_body == J_world

    where J_world is the stacked (position, rotation) Jacobian
    from mj_jacSite.

    Args:
        model:   MuJoCo model.
        data:    MuJoCo data (after mj_forward).
        site_id: integer site ID.
    Returns: (6, nv) body-frame Jacobian.
    """
    ...


def compute_collision_constraint(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom1_id: int,
    geom2_id: int,
    min_dist: float,
    dt: float,
    gain: float,
    detection_dist: float,
) -> tuple:
    """Collision-avoidance linear inequality  g @ dq <= h  for one geom pair.

    The constraint must resist motions that bring geoms closer
    and allow motions that separate them.

    Returns (zeros, +inf) when the pair is beyond detection range.

    Args:
        geom1_id, geom2_id: geom pair.
        min_dist:  minimum allowed distance.
        dt:        integration timestep.
        gain:      approach-rate gain in (0, 1].
        detection_dist: maximum distance at which constraint activates.
    Returns:
        (g_row, h_val) -- g_row shape (nv,), h_val scalar.
    """
    ...


def solve_ik_step(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    site_id: int,
    T_target: np.ndarray,
    dt: float,
    damping: float,
    collision_pairs: list,
    min_collision_dist: float,
    gain: float,
) -> np.ndarray:
    """One step of differential IK with optional collision avoidance.

    Computes a joint velocity that reduces the task-space error
    while respecting collision constraints.

    Args:
        collision_pairs: list of (geom1_id, geom2_id) tuples.
    Returns: (nv,) velocity vector.
    """
    ...
