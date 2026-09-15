"""Acrobot swing-up controller: energy-based swing-up with q2 regulation,
exponential torque smoothing, and LQR stabilization.

Strategy:
1. Kickstart: brief constant torque to escape the zero-velocity rest state.
2. Energy swing-up with regulation: tau = -k_e*(E-E_target)*qd2
   combined with -k_p2*sin(q2) - k_d2*qd2 to prevent the elbow from
   spinning freely. An exponential moving-average filter smooths the
   torque output.
3. LQR stabilization: when the state enters a ball around [pi,0,0,0],
   switch to u = -K*dx computed from the CARE solution of the linearized
   dynamics at the inverted equilibrium.
"""

import math
import numpy as np
from scipy.linalg import solve_continuous_are


class AcrobotController:
    def __init__(self, plant, params):
        self.plant = plant
        self.params = params
        self.goal = params['goal']
        self.E_target = plant.total_energy(self.goal)

        # LQR gains
        self.K = self._compute_lqr()

        # Swing-up tuning
        self.k_e = 8.0           # energy pumping gain
        self.k_p2 = 7.0          # q2 restoring gain
        self.k_d2 = 0.1          # q2 damping gain

        # LQR switching thresholds
        self.lqr_q = 0.5         # angle threshold [rad]
        self.lqr_qd = 4.0        # velocity threshold [rad/s]

        # Torque smoothing (exponential moving average)
        self.alpha = 0.2
        self._prev_tau = 0.0

    # ---- LQR ----

    def _compute_lqr(self):
        x0 = list(self.goal)
        u0 = 0.0
        eps = 1e-6
        n = 4

        A = np.zeros((n, n))
        B = np.zeros((n, 1))

        for j in range(n):
            xp = list(x0); xp[j] += eps
            xm = list(x0); xm[j] -= eps
            fp = self.plant.forward_dynamics(xp, u0)
            fm = self.plant.forward_dynamics(xm, u0)
            for i in range(n):
                A[i, j] = (fp[i] - fm[i]) / (2.0 * eps)

        fp = self.plant.forward_dynamics(x0, u0 + eps)
        fm = self.plant.forward_dynamics(x0, u0 - eps)
        for i in range(n):
            B[i, 0] = (fp[i] - fm[i]) / (2.0 * eps)

        Q = np.diag([5.0, 5.0, 0.5, 0.5])
        R = np.array([[5.0]])

        P = solve_continuous_are(A, B, Q, R)
        K = np.linalg.solve(R, B.T @ P)
        return K[0].tolist()

    # ---- control law ----

    def get_control_output(self, state, t):
        q1, q2, q1d, q2d = state
        dq1 = abs(self._wrap(q1 - self.goal[0]))
        dq2 = abs(self._wrap(q2 - self.goal[1]))

        # Choose raw torque
        if (dq1 < self.lqr_q
                and dq2 < self.lqr_q + 0.1
                and abs(q1d) < self.lqr_qd
                and abs(q2d) < self.lqr_qd):
            tau_raw = self._lqr(state)
        elif abs(q1d) + abs(q2d) < 0.05 and t < 0.5:
            tau_raw = self.plant.tau_max          # kickstart
        else:
            tau_raw = self._energy_swingup(state)

        tau_raw = self._clamp(tau_raw)

        # Exponential smoothing
        tau = self.alpha * tau_raw + (1.0 - self.alpha) * self._prev_tau
        self._prev_tau = tau
        return tau

    def _lqr(self, state):
        q1, q2, q1d, q2d = state
        dx = [self._wrap(q1 - self.goal[0]),
              self._wrap(q2 - self.goal[1]),
              q1d - self.goal[2],
              q2d - self.goal[3]]
        return -sum(self.K[i] * dx[i] for i in range(4))

    def _energy_swingup(self, state):
        q1, q2, q1d, q2d = state
        E = self.plant.total_energy(state)
        E_err = E - self.E_target

        tau_energy = -self.k_e * E_err * q2d
        tau_reg = -self.k_p2 * math.sin(q2) - self.k_d2 * q2d
        return tau_energy + tau_reg

    # ---- helpers ----

    def _clamp(self, tau):
        return max(-self.plant.tau_max, min(self.plant.tau_max, tau))

    @staticmethod
    def _wrap(angle):
        return ((angle + math.pi) % (2.0 * math.pi)) - math.pi
