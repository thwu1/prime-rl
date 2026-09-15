"""
Double pendulum plant dynamics.

Implements the Euler-Lagrange equations for a planar double pendulum with
mass matrix, Coriolis, gravity, friction, forward/inverse dynamics,
forward kinematics, and energy computation.

Convention: q1=0, q2=0 is the hanging-down position. q1=pi, q2=0 is upright.
Angles measured from the free-hanging vertical (positive counter-clockwise).

Reference: Underactuated Lecture formulation (see docs for full equations).
"""
import numpy as np


class DoublePendulumPlant:
    """
    Numerical double pendulum plant.

    Parameters
    ----------
    m1, m2 : float — link masses [kg]
    l1, l2 : float — link lengths [m]
    r1, r2 : float — center-of-mass distances from parent joint [m]
    I1, I2 : float — link inertias about their CoM [kg*m^2]
    Ir     : float — motor inertia [kg*m^2]
    gr     : int   — gear ratio
    g      : float — gravitational acceleration [m/s^2]
    b1, b2 : float — viscous damping [kg*m/s]
    cf1, cf2 : float — Coulomb friction [Nm]
    torque_limit : tuple(float, float) — max torque per joint [Nm]
    """

    def __init__(self, m1, m2, l1, l2, r1, r2, I1, I2,
                 Ir=0.0, gr=6, g=9.81,
                 b1=0.0, b2=0.0, cf1=0.0, cf2=0.0,
                 torque_limit=(0.0, 6.0)):
        self.m1 = m1
        self.m2 = m2
        self.l1 = l1
        self.l2 = l2
        self.r1 = r1
        self.r2 = r2
        self.I1 = I1
        self.I2 = I2
        self.Ir = Ir
        self.gr = gr
        self.g = g
        self.b1 = b1
        self.b2 = b2
        self.cf1 = cf1
        self.cf2 = cf2
        self.torque_limit = torque_limit

        # Actuator selection matrix
        if torque_limit[0] == 0.0 and torque_limit[1] > 0:
            # Acrobot: only joint 2 actuated
            self.B = np.array([[0.0, 0.0], [0.0, 1.0]])
        elif torque_limit[1] == 0.0 and torque_limit[0] > 0:
            # Pendubot: only joint 1 actuated
            self.B = np.array([[1.0, 0.0], [0.0, 0.0]])
        else:
            # Fully actuated
            self.B = np.array([[1.0, 0.0], [0.0, 1.0]])

    def mass_matrix(self, x):
        """Return 2x2 mass matrix M(q)."""
        q2 = x[1]
        c2 = np.cos(q2)

        M11 = (self.I1 + self.I2
               + self.m2 * self.l1 ** 2
               + 2.0 * self.m2 * self.l1 * self.r2 * c2
               + self.gr ** 2 * self.Ir + self.Ir)
        M12 = (self.I2
               + self.m2 * self.l1 * self.r2 * c2
               - self.gr * self.Ir)
        M22 = self.I2 + self.gr ** 2 * self.Ir

        return np.array([[M11, M12],
                         [M12, M22]])

    def coriolis_matrix(self, x):
        """Return 2x2 Coriolis matrix C(q, qd)."""
        q2, qd1, qd2 = x[1], x[2], x[3]
        h = self.m2 * self.l1 * self.r2 * np.sin(q2)

        return np.array([[-2.0 * h * qd2, -h * qd2],
                         [h * qd1,         0.0]])

    def gravity_vector(self, x):
        """Return 2-element gravity vector G(q)."""
        q1, q2 = x[0], x[1]
        s1 = np.sin(q1)
        s12 = np.sin(q1 + q2)

        G1 = (-self.m1 * self.g * self.r1 * s1
              - self.m2 * self.g * (self.l1 * s1 + self.r2 * s12))
        G2 = -self.m2 * self.g * self.r2 * s12

        return np.array([G1, G2])

    def friction_vector(self, x):
        """Return 2-element friction vector F(qd)."""
        qd1, qd2 = x[2], x[3]
        F1 = self.b1 * qd1 + self.cf1 * np.arctan(100.0 * qd1)
        F2 = self.b2 * qd2 + self.cf2 * np.arctan(100.0 * qd2)
        return np.array([F1, F2])

    def forward_dynamics(self, x, u):
        """
        Compute joint accelerations: qdd = M^{-1}(Bu - Cqd + G - F).

        Parameters
        ----------
        x : array, shape=(4,) — [q1, q2, qd1, qd2]
        u : array, shape=(2,) — [u1, u2]

        Returns
        -------
        array, shape=(2,) — [qdd1, qdd2]
        """
        vel = x[2:]
        M = self.mass_matrix(x)
        C = self.coriolis_matrix(x)
        G = self.gravity_vector(x)
        F = self.friction_vector(x)

        Minv = np.linalg.inv(M)
        force = self.B @ u - C @ vel + G - F
        return Minv @ force

    def rhs(self, t, x, u):
        """
        State derivative: dx/dt = [qd1, qd2, qdd1, qdd2].

        Parameters
        ----------
        t : float — time (unused, kept for interface)
        x : array, shape=(4,) — state
        u : array, shape=(2,) — torques

        Returns
        -------
        array, shape=(4,)
        """
        accn = self.forward_dynamics(x, u)
        return np.array([x[2], x[3], accn[0], accn[1]])

    def forward_kinematics(self, pos):
        """
        End-effector (tip of link 2) Cartesian position.

        Parameters
        ----------
        pos : array, shape=(2,) — [q1, q2]

        Returns
        -------
        (ee_x, ee_y) : floats — position relative to mount point [m]
        """
        q1, q2 = pos[0], pos[1]
        ee_x = self.l1 * np.sin(q1) + self.l2 * np.sin(q1 + q2)
        ee_y = -self.l1 * np.cos(q1) - self.l2 * np.cos(q1 + q2)
        return ee_x, ee_y

    def kinetic_energy(self, x):
        """Kinetic energy: 0.5 * qd^T M qd."""
        M = self.mass_matrix(x)
        qd = x[2:]
        return 0.5 * qd @ M @ qd

    def potential_energy(self, x):
        """Potential energy (zero at mount point height)."""
        q1, q2 = x[0], x[1]
        h1 = -self.r1 * np.cos(q1)
        h2 = -self.l1 * np.cos(q1) - self.r2 * np.cos(q1 + q2)
        return self.m1 * self.g * h1 + self.m2 * self.g * h2

    def total_energy(self, x):
        """Total mechanical energy E = Ekin + Epot."""
        return self.kinetic_energy(x) + self.potential_energy(x)
