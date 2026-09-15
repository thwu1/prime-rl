"""Double pendulum plant model for the acrobot configuration.

Implements the equations of motion using the Lagrangian formulation:
    M(q) * qdd = -C(q,qd) * qd + G(q) + B * u - F(qd)

State: x = [q1, q2, q1_dot, q2_dot]
    q1: shoulder angle (measured from hanging down)
    q2: elbow angle (relative angle between links)
Convention: q1=0, q2=0 is hanging down; q1=pi, q2=0 is inverted upright.
"""

import math
import json


class DoublePendulumPlant:
    def __init__(self, params):
        self.m1 = params['m1']
        self.m2 = params['m2']
        self.l1 = params['l1']
        self.l2 = params['l2']
        self.r1 = params['r1']
        self.r2 = params['r2']
        self.I1 = params['I1']
        self.I2 = params['I2']
        self.b1 = params.get('b1', 0.0)
        self.b2 = params.get('b2', 0.0)
        self.cf1 = params.get('cf1', 0.0)
        self.cf2 = params.get('cf2', 0.0)
        self.g = params.get('gravity', 9.81)
        self.tau_max = params.get('tau_max', 6.0)

    def mass_matrix(self, q2):
        """2x2 inertia matrix M(q2). Returns [[M11, M12], [M21, M22]]."""
        c2 = math.cos(q2)
        a = self.m2 * self.l1 * self.r2 * c2
        M11 = self.I1 + self.I2 + self.m2 * self.l1 ** 2 + 2.0 * a
        M12 = self.I2 + a
        M22 = self.I2
        return [[M11, M12], [M12, M22]]

    def coriolis_vector(self, q2, q1d, q2d):
        """Coriolis/centrifugal force vector C(q,qd)*qd."""
        s2 = math.sin(q2)
        h = self.m2 * self.l1 * self.r2 * s2
        c1 = -h * (2.0 * q1d * q2d + q2d * q2d)
        c2 = h * q1d * q1d
        return [c1, c2]

    def gravity_vector(self, q1, q2):
        """Gravity torque vector G(q). Appears on RHS: M*qdd = ... + G ..."""
        s1 = math.sin(q1)
        s12 = math.sin(q1 + q2)
        g1 = -(self.m1 * self.g * self.r1 * s1
               + self.m2 * self.g * (self.l1 * s1 + self.r2 * s12))
        g2 = -self.m2 * self.g * self.r2 * s12
        return [g1, g2]

    def friction_vector(self, q1d, q2d):
        """Friction torque: viscous (b*qd) + Coulomb (cf*atan(100*qd))."""
        f1 = self.b1 * q1d + self.cf1 * math.atan(100.0 * q1d)
        f2 = self.b2 * q2d + self.cf2 * math.atan(100.0 * q2d)
        return [f1, f2]

    def forward_dynamics(self, state, tau):
        """Compute dx/dt = f(x, u).

        Args:
            state: [q1, q2, q1_dot, q2_dot]
            tau: scalar torque at joint 2 (acrobot configuration)

        Returns:
            [q1_dot, q2_dot, q1_ddot, q2_ddot]
        """
        q1, q2, q1d, q2d = state

        tau = max(-self.tau_max, min(self.tau_max, tau))

        M = self.mass_matrix(q2)
        C = self.coriolis_vector(q2, q1d, q2d)
        G = self.gravity_vector(q1, q2)
        F = self.friction_vector(q1d, q2d)

        # M * qdd = -C + G + B*u - F   (acrobot: B = [[0],[1]])
        rhs0 = -C[0] + G[0] - F[0]
        rhs1 = -C[1] + G[1] - F[1] + tau

        det = M[0][0] * M[1][1] - M[0][1] * M[1][0]
        q1dd = (M[1][1] * rhs0 - M[0][1] * rhs1) / det
        q2dd = (-M[1][0] * rhs0 + M[0][0] * rhs1) / det

        return [q1d, q2d, q1dd, q2dd]

    def potential_energy(self, q1, q2):
        """Gravitational potential energy V(q)."""
        h1 = -self.r1 * math.cos(q1)
        h2 = -self.l1 * math.cos(q1) - self.r2 * math.cos(q1 + q2)
        return self.m1 * self.g * h1 + self.m2 * self.g * h2

    def kinetic_energy(self, q2, q1d, q2d):
        """Kinetic energy T(q, qd) = 0.5 * qd^T M qd."""
        M = self.mass_matrix(q2)
        return 0.5 * (M[0][0] * q1d ** 2
                      + 2.0 * M[0][1] * q1d * q2d
                      + M[1][1] * q2d ** 2)

    def total_energy(self, state):
        """Total mechanical energy E = T + V."""
        q1, q2, q1d, q2d = state
        return self.kinetic_energy(q2, q1d, q2d) + self.potential_energy(q1, q2)

    def end_effector_y(self, q1, q2):
        """Y-coordinate of end effector (tip of link 2), positive upward."""
        return -self.l1 * math.cos(q1) - self.l2 * math.cos(q1 + q2)

    @classmethod
    def from_json(cls, path):
        with open(path) as f:
            return cls(json.load(f))
