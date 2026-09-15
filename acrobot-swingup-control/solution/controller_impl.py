
"""
Acrobot swing-up + stabilization controller.

Phase 1 — Energy-based swing-up:
    Pumps mechanical energy toward the unstable equilibrium level using
        u2 = -ke * (E - E_desired) * qd2
    with a periodic excitation term to escape the initial rest state.

Phase 2 — LQR stabilization:
    Near the upright position, switches to an infinite-horizon LQR designed
    from the numerically linearized dynamics and the continuous algebraic
    Riccati equation (CARE).

Switching uses the LQR cost-to-go with hysteresis to prevent chattering.
"""
import numpy as np
from scipy.linalg import solve_continuous_are


class MyController:
    def __init__(self, plant):
        self.plant = plant

        # Goal state
        self.x_goal = np.array([np.pi, 0.0, 0.0, 0.0])

        # Energy at the unstable equilibrium
        self.E_desired = plant.total_energy(self.x_goal)

        # ── swing-up gains ──
        self.ke = 10.0          # energy-pumping gain
        self.epsilon = 4.0      # excitation amplitude [Nm]
        self.omega = 4.5        # excitation frequency [rad/s]

        # ── LQR design ──
        A, B_full = self._linearize(self.x_goal, np.array([0.0, 0.0]))
        # Keep only the u2 column (acrobot: u1 ≡ 0)
        B_u2 = B_full[:, 1:2]

        Q = np.diag([20.0, 20.0, 1.0, 1.0])
        R = np.array([[0.5]])

        self.P = solve_continuous_are(A, B_u2, Q, R)
        self.K = np.linalg.solve(R, B_u2.T @ self.P)  # shape (1, 4)

        # ── switching thresholds (hysteresis) ──
        self.use_lqr = False
        self.V_enter = 80.0     # switch TO LQR when cost-to-go < V_enter
        self.V_exit = 160.0     # switch FROM LQR when cost-to-go > V_exit

    # ──────────────────────────────────────────────────────────────────
    def _linearize(self, x0, u0, eps=1e-6):
        """Numerical linearization via central finite differences."""
        n = len(x0)
        m = len(u0)

        A = np.zeros((n, n))
        for j in range(n):
            dx = np.zeros(n)
            dx[j] = eps
            fp = self.plant.rhs(0.0, x0 + dx, u0)
            fm = self.plant.rhs(0.0, x0 - dx, u0)
            A[:, j] = (fp - fm) / (2.0 * eps)

        B = np.zeros((n, m))
        for j in range(m):
            du = np.zeros(m)
            du[j] = eps
            fp = self.plant.rhs(0.0, x0, u0 + du)
            fm = self.plant.rhs(0.0, x0, u0 - du)
            B[:, j] = (fp - fm) / (2.0 * eps)

        return A, B

    @staticmethod
    def _wrap(angle):
        """Wrap angle to [-pi, pi]."""
        return (angle + np.pi) % (2.0 * np.pi) - np.pi

    # ──────────────────────────────────────────────────────────────────
    def get_control_output(self, x, t):
        x_err = x.copy() - self.x_goal
        x_err[0] = self._wrap(x_err[0])
        x_err[1] = self._wrap(x_err[1])

        V = x_err @ self.P @ x_err      # LQR cost-to-go

        # ── switching logic with hysteresis ──
        if self.use_lqr:
            if V > self.V_exit:
                self.use_lqr = False
            else:
                u2 = float(-(self.K @ x_err)[0])
                return [0.0, np.clip(u2, -self.plant.torque_limit[1],
                                          self.plant.torque_limit[1])]
        else:
            if V < self.V_enter:
                self.use_lqr = True
                u2 = float(-(self.K @ x_err)[0])
                return [0.0, np.clip(u2, -self.plant.torque_limit[1],
                                          self.plant.torque_limit[1])]

        # ── energy-based swing-up ──
        E = self.plant.total_energy(x)
        dE = E - self.E_desired

        # Energy pumping: drives E → E_desired
        u2 = -self.ke * dE * x[3]

        # Periodic excitation to break initial rest equilibrium
        u2 += self.epsilon * np.cos(self.omega * t)

        u2 = np.clip(u2, -self.plant.torque_limit[1],
                           self.plant.torque_limit[1])
        return [0.0, float(u2)]
