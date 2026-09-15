"""
Constraint equations and Jacobians for the spatial double pendulum.


Constraints (6 total, all holonomic):
  C1 (3 eqs): Spherical joint 1 — top of link1 coincides with fixed pivot
  C2 (3 eqs): Spherical joint 2 — bottom of link1 coincides with top of link2

Quaternion unit-norm is NOT a DAE constraint; it is enforced by algebraic
renormalization after each position update.

The constraint Jacobian Phi_v is the 6x12 matrix of partial derivatives
of the constraint velocity equations with respect to generalized velocities.

For a spherical joint constraining body-local point s on body i to a target:
    C = r_i + R_i * s_i - target
Taking the time derivative (omega in body frame):
    dC/dt = v_i + R_i * (omega_i x s_i) = v_i - R_i * skew(s_i) * omega_i

So the Jacobian rows w.r.t. body i's velocities are:
    dC/dv_i = I_3
    dC/domega_i = -R_i * skew(s_i)
"""

import numpy as np
from bodies import quat_to_rotation, skew


def compute_constraints(system):
    """
    Evaluate the 6 constraint equations.
    Returns a 6-vector of constraint violations.
    """
    C = np.zeros(6)

    link1 = system.link1
    link2 = system.link2

    # --- C1: Spherical joint 1 (link1 top = pivot) ---
    R1 = link1.get_rotation_matrix()
    top1_global = link1.pos + R1 @ system.link1_top_local
    C[0:3] = top1_global - system.pivot

    # --- C2: Spherical joint 2 (link1 bottom = link2 top) ---
    bot1_global = link1.pos + R1 @ system.link1_bot_local
    R2 = link2.get_rotation_matrix()
    top2_global = link2.pos + R2 @ system.link2_top_local
    C[3:6] = bot1_global - top2_global

    return C


def compute_constraint_velocity(system):
    """
    Evaluate the time derivative of constraints: dC/dt = Phi_v * v
    Returns a 6-vector.
    """
    Phi_v = compute_jacobian(system)
    v = system.get_all_velocities()
    return Phi_v @ v


def compute_jacobian(system):
    """
    Compute the constraint Jacobian Phi_v (6 x 12) with respect to
    generalized velocities v = [v1, omega1, v2, omega2].

    TODO: Fill in the Jacobian matrix below. Currently returns zeros,
    which will cause the Newton solver to fail.

    Velocity ordering: [v1(3), omega1(3), v2(3), omega2(3)]
      indices:          0:3    3:6         6:9    9:12

    Constraint ordering:
      C1 (rows 0:3): spherical joint 1 — link1 top = pivot
      C2 (rows 3:6): spherical joint 2 — link1 bot = link2 top

    For a spherical joint constraining local point s on body i:
        dC/dt = v_i - R_i * skew(s_i) * omega_i
    So:
        dC/dv_i = I_3          (3x3 identity)
        dC/domega_i = -R_i * skew(s_i)

    For joint 2 (connecting two bodies), body 2 enters with opposite sign:
        C2 = (r1 + R1*s1_bot) - (r2 + R2*s2_top)
        dC2/dt = v1 - R1*skew(s1_bot)*omega1 - v2 + R2*skew(s2_top)*omega2
    So:
        dC2/dv1 = I_3
        dC2/domega1 = -R1*skew(s1_bot)
        dC2/dv2 = -I_3
        dC2/domega2 = R2*skew(s2_top)

    Hints:
      - Use skew() for cross-product matrices
      - Use body.get_rotation_matrix() for R
      - system.link1_top_local, link1_bot_local, link2_top_local for s vectors
    """
    Phi_v = np.zeros((6, 12))

    # ========================================================
    # TODO: Implement the constraint Jacobian
    # ========================================================

    return Phi_v


def compute_gamma(system):
    """
    Compute the gamma vector: the right-hand side acceleration-level term.
    gamma = -d(Phi_v)/dt * v  (the quadratic velocity term)

    At the acceleration level: Phi_v * a = gamma
    where gamma = -Phi_v_dot * v

    For spherical joints, gamma_i = R_i * (omega_i x (omega_i x s_i))
    This is the centripetal acceleration term.
    """
    gamma = np.zeros(6)

    link1 = system.link1
    link2 = system.link2
    R1 = link1.get_rotation_matrix()
    R2 = link2.get_rotation_matrix()

    # Spherical joint 1: gamma = R1 * (omega1 x (omega1 x s1_top))
    s1_top = system.link1_top_local
    omega1 = link1.omega
    gamma[0:3] = R1 @ np.cross(omega1, np.cross(omega1, s1_top))

    # Spherical joint 2:
    s1_bot = system.link1_bot_local
    s2_top = system.link2_top_local
    omega2 = link2.omega
    gamma[3:6] = (R1 @ np.cross(omega1, np.cross(omega1, s1_bot))
                  - R2 @ np.cross(omega2, np.cross(omega2, s2_top)))

    return gamma
