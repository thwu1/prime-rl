"""
Deterministic RK4 simulator for the double pendulum.
"""
import numpy as np


class Simulator:
    """
    Simulates the double pendulum under a controller using RK4 integration.

    Parameters
    ----------
    plant : DoublePendulumPlant
    """

    def __init__(self, plant):
        self.plant = plant

    def _rk4_step(self, x, t, u, dt):
        """Single Runge-Kutta 4 integration step."""
        k1 = self.plant.rhs(t, x, u)
        k2 = self.plant.rhs(t + 0.5 * dt, x + 0.5 * dt * k1, u)
        k3 = self.plant.rhs(t + 0.5 * dt, x + 0.5 * dt * k2, u)
        k4 = self.plant.rhs(t + dt, x + dt * k3, u)
        return x + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

    def simulate(self, controller, x0, dt, t_final):
        """
        Run a closed-loop simulation.

        Parameters
        ----------
        controller : object with get_control_output(x, t) -> [u1, u2]
        x0 : array-like, shape=(4,) — initial state
        dt : float — integration timestep [s]
        t_final : float — simulation duration [s]

        Returns
        -------
        T : ndarray, shape=(N+1,) — time points
        X : ndarray, shape=(N+1, 4) — states
        U : ndarray, shape=(N, 2) — applied torques (after clipping)
        """
        x = np.array(x0, dtype=float)
        t = 0.0

        T_list = [t]
        X_list = [x.copy()]
        U_list = []

        n_steps = int(round(t_final / dt))
        tl = self.plant.torque_limit

        for _ in range(n_steps):
            u = np.array(controller.get_control_output(x, t), dtype=float)

            # Enforce torque limits
            u[0] = np.clip(u[0], -tl[0], tl[0])
            u[1] = np.clip(u[1], -tl[1], tl[1])

            U_list.append(u.copy())
            x = self._rk4_step(x, t, u, dt)
            t += dt

            T_list.append(t)
            X_list.append(x.copy())

        return np.array(T_list), np.array(X_list), np.array(U_list)
