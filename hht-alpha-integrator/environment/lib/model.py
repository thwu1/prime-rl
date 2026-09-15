"""
Planar double pendulum model using redundant Cartesian coordinates.

Each rigid link is modeled with 3 DOFs: center-of-gravity position (x, y)
and rotation angle theta (measured CCW from the positive x-axis).
  theta = -pi/2 corresponds to hanging straight down.

Generalized coordinates: q = [x1, y1, theta1, x2, y2, theta2]

Constraints (4 holonomic):
  - Pin joint at origin connecting ground to left end of body 1 (2 eqs)
  - Pin joint connecting right end of body 1 to left end of body 2 (2 eqs)

This yields 6 - 4 = 2 degrees of freedom.

Equations of motion (index-3 DAE):
    M * a + Phi_q(q)^T * lambda = F(t, q, v)
    Phi(q) = 0

where M is the constant mass matrix, F the applied force vector (gravity),
Phi the constraint vector, and Phi_q its Jacobian.
"""

import numpy as np


class DoublePendulum:
    """Planar double pendulum with pin joints, modeled as an index-3 DAE."""

    def __init__(self, L1=1.0, L2=1.0, m1=1.0, m2=1.0, g=9.81):
        self.L1 = L1
        self.L2 = L2
        self.m1 = m1
        self.m2 = m2
        self.g = g
        self.I1 = m1 * L1**2 / 12.0  # moment of inertia of uniform rod about CoG
        self.I2 = m2 * L2**2 / 12.0
        self.n_q = 6  # number of generalized coordinates
        self.n_c = 4  # number of constraints

    def mass_matrix(self):
        """Return the constant 6x6 diagonal mass matrix."""
        return np.diag([self.m1, self.m1, self.I1,
                        self.m2, self.m2, self.I2])

    def forces(self, t, q, v):
        """Return the 6-vector of applied forces (gravity only)."""
        F = np.zeros(self.n_q)
        F[1] = -self.m1 * self.g
        F[4] = -self.m2 * self.g
        return F

    def constraints(self, q):
        """
        Evaluate the 4 constraint equations Phi(q).

        Phi[0:2]: pin joint at origin (ground -> left end of body 1)
        Phi[2:4]: pin joint (right end of body 1 -> left end of body 2)
        """
        x1, y1, t1, x2, y2, t2 = q
        L1, L2 = self.L1, self.L2

        Phi = np.zeros(self.n_c)
        # Ground-body1 pin joint
        Phi[0] = x1 - (L1 / 2) * np.cos(t1)
        Phi[1] = y1 - (L1 / 2) * np.sin(t1)
        # Body1-body2 pin joint
        Phi[2] = x1 + (L1 / 2) * np.cos(t1) - x2 + (L2 / 2) * np.cos(t2)
        Phi[3] = y1 + (L1 / 2) * np.sin(t1) - y2 + (L2 / 2) * np.sin(t2)
        return Phi

    def constraint_jacobian(self, q):
        """Evaluate the 4x6 constraint Jacobian Phi_q(q)."""
        x1, y1, t1, x2, y2, t2 = q
        L1, L2 = self.L1, self.L2

        Phi_q = np.zeros((self.n_c, self.n_q))

        # dPhi0/dq
        Phi_q[0, 0] = 1.0
        Phi_q[0, 2] = (L1 / 2) * np.sin(t1)

        # dPhi1/dq
        Phi_q[1, 1] = 1.0
        Phi_q[1, 2] = -(L1 / 2) * np.cos(t1)

        # dPhi2/dq
        Phi_q[2, 0] = 1.0
        Phi_q[2, 2] = -(L1 / 2) * np.sin(t1)
        Phi_q[2, 3] = -1.0
        Phi_q[2, 5] = -(L2 / 2) * np.sin(t2)

        # dPhi3/dq
        Phi_q[3, 1] = 1.0
        Phi_q[3, 2] = (L1 / 2) * np.cos(t1)
        Phi_q[3, 4] = -1.0
        Phi_q[3, 5] = (L2 / 2) * np.cos(t2)

        return Phi_q

    def gamma(self, q, v):
        """
        Quadratic velocity vector for acceleration-level constraints.

        Defined such that the acceleration-level constraint equation is:
            Phi_q * a + gamma(q, v) = 0

        where gamma_i = sum_{j,k} (d^2 Phi_i / dq_j dq_k) * v_j * v_k
        """
        x1, y1, t1, x2, y2, t2 = q
        L1, L2 = self.L1, self.L2
        vt1 = v[2]  # theta1_dot
        vt2 = v[5]  # theta2_dot

        gam = np.zeros(self.n_c)
        gam[0] = (L1 / 2) * np.cos(t1) * vt1**2
        gam[1] = (L1 / 2) * np.sin(t1) * vt1**2
        gam[2] = -(L1 / 2) * np.cos(t1) * vt1**2 - (L2 / 2) * np.cos(t2) * vt2**2
        gam[3] = -(L1 / 2) * np.sin(t1) * vt1**2 - (L2 / 2) * np.sin(t2) * vt2**2
        return gam

    def consistent_initial_conditions(self, theta1_0, theta2_0,
                                       omega1_0=0.0, omega2_0=0.0):
        """
        Compute consistent Cartesian initial conditions from minimal coordinates.

        Parameters:
            theta1_0: initial angle of body 1 (from positive x-axis)
            theta2_0: initial angle of body 2 (from positive x-axis)
            omega1_0: initial angular velocity of body 1
            omega2_0: initial angular velocity of body 2

        Returns: (q0, v0) — position and velocity vectors satisfying constraints
        """
        L1, L2 = self.L1, self.L2

        # Body 1 CoG
        x1 = (L1 / 2) * np.cos(theta1_0)
        y1 = (L1 / 2) * np.sin(theta1_0)

        # Tip of body 1 (= attachment point for body 2)
        tip_x = L1 * np.cos(theta1_0)
        tip_y = L1 * np.sin(theta1_0)

        # Body 2 CoG
        x2 = tip_x + (L2 / 2) * np.cos(theta2_0)
        y2 = tip_y + (L2 / 2) * np.sin(theta2_0)

        q0 = np.array([x1, y1, theta1_0, x2, y2, theta2_0])

        # Velocities (time derivatives of the position expressions)
        vx1 = -(L1 / 2) * np.sin(theta1_0) * omega1_0
        vy1 = (L1 / 2) * np.cos(theta1_0) * omega1_0
        vx2 = -L1 * np.sin(theta1_0) * omega1_0 - (L2 / 2) * np.sin(theta2_0) * omega2_0
        vy2 = L1 * np.cos(theta1_0) * omega1_0 + (L2 / 2) * np.cos(theta2_0) * omega2_0

        v0 = np.array([vx1, vy1, omega1_0, vx2, vy2, omega2_0])

        return q0, v0

    def kinetic_energy(self, q, v):
        """Compute the kinetic energy T = 0.5 * v^T M v."""
        M = self.mass_matrix()
        return 0.5 * v @ M @ v

    def potential_energy(self, q):
        """Compute the gravitational potential energy (reference: y=0)."""
        return self.m1 * self.g * q[1] + self.m2 * self.g * q[4]

    def total_energy(self, q, v):
        """Compute total mechanical energy E = T + V."""
        return self.kinetic_energy(q, v) + self.potential_energy(q)
