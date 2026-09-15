"""
Double Compound Pendulum Simulator

Implements Lagrangian dynamics for a planar double pendulum
consisting of two uniform rigid rods connected by revolute joints.

Convention:
    q1: angle of link 1 from downward vertical (rad, positive = counterclockwise)
    q2: relative angle of link 2 w.r.t. link 1 (rad, positive = counterclockwise)

Physical parameters:
    m1, m2: link masses (kg)
    l1, l2: link lengths (m)
    b1, b2: viscous damping coefficients at joints (N*m*s/rad)

The center of mass of each link is at its midpoint (uniform rod).
The moment of inertia about the COM is I_i = m_i * l_i^2 / 12.

Equations of motion via Lagrangian formulation:
    M(q) * qdd + C(q, qd) + G(q) + D(qd) = tau_ext

    M: 2x2 symmetric positive-definite mass matrix
    C: Coriolis/centrifugal force vector (computed via Christoffel symbols)
    G: gravity torque vector (partial derivatives of potential energy)
    D: viscous damping torque vector

Integration: semi-implicit Euler (symplectic).
"""

import math
import json


def compute_accelerations(q1, q2, qd1, qd2, m1, m2, l1, l2, b1, b2, g):
    """
    Compute joint angular accelerations from the equations of motion.

    For free swinging (no external torque):
        M(q) * qdd = -C(q, qd) - G(q) - D(qd)
    """
    lc1 = l1 / 2.0
    lc2 = l2 / 2.0
    I1 = m1 * l1 * l1 / 12.0
    I2 = m2 * l2 * l2 / 12.0

    cos_q2 = math.cos(q2)
    sin_q2 = math.sin(q2)

    # Mass matrix M(q) - symmetric 2x2
    a11 = m1 * lc1 * lc1 + I1 + m2 * (l1 * l1 + lc2 * lc2 + 2.0 * l1 * lc2 * cos_q2) + I2
    a12 = m2 * lc2 * lc2 + I2 + m2 * l1 * lc2 * cos_q2
    a22 = m2 * lc2 * lc2 + I2

    # Coriolis/centrifugal vector C(q, qd) via Christoffel symbols
    h = m2 * l1 * lc2 * sin_q2
    coriolis_1 = -h * qd2 * (2.0 * qd1 + qd2)
    coriolis_2 = h * qd1 * qd1

    # Gravity torque vector G(q) = dV/dq
    sin_q1 = math.sin(q1)
    sin_q12 = math.sin(q1 + q2)
    grav_1 = (m1 * lc1 + m2 * l1) * g * sin_q1 + m2 * lc2 * g * sin_q12
    grav_2 = m2 * lc2 * g * sin_q12

    # Viscous damping D(qd) = [b1*qd1, b2*qd2]
    damp_1 = b1 * qd1
    damp_2 = b2 * qd2

    # Right-hand side: M*qdd = -(C + G + D)
    rhs1 = -coriolis_1 - grav_1 - damp_1
    rhs2 = -coriolis_2 - grav_2 - damp_2

    # Solve 2x2 symmetric linear system via Cramer's rule
    det = a11 * a22 - a12 * a12
    qdd1 = (a22 * rhs1 - a12 * rhs2) / det
    qdd2 = (-a12 * rhs1 + a11 * rhs2) / det

    return qdd1, qdd2


def simulate(q1_0, q2_0, qd1_0, qd2_0, m1, m2, l1, l2, b1, b2, g, dt, n_steps):
    """
    Run forward simulation using semi-implicit Euler integration.

    The semi-implicit (symplectic) Euler method updates velocity first,
    then uses the new velocity to update position:
        qd^{n+1} = qd^n + dt * qdd^n
        q^{n+1}  = q^n  + dt * qd^{n+1}

    Returns list of states [[q1, q2, qd1, qd2], ...] at each timestep,
    including the initial state (total length = n_steps + 1).
    """
    states = []
    q1, q2 = q1_0, q2_0
    qd1, qd2 = qd1_0, qd2_0

    for step in range(n_steps + 1):
        states.append([q1, q2, qd1, qd2])
        if step < n_steps:
            qdd1, qdd2 = compute_accelerations(
                q1, q2, qd1, qd2, m1, m2, l1, l2, b1, b2, g
            )
            # Semi-implicit Euler: velocity update first
            qd1 = qd1 + dt * qdd1
            qd2 = qd2 + dt * qdd2
            q1 = q1 + dt * qd1
            q2 = q2 + dt * qd2

    return states


def load_config(path):
    """Load simulation configuration from a JSON file."""
    with open(path) as f:
        return json.load(f)
