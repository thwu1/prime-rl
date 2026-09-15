"""RK4 simulation engine for the double pendulum."""


def simulate(plant, controller, params):
    """Run a 4th-order Runge-Kutta simulation.

    Args:
        plant: DoublePendulumPlant instance
        controller: object with get_control_output(state, t) -> float
        params: dict with 'dt', 'T', 'initial_state'

    Returns:
        list of (t, q1, q2, q1d, q2d, tau) tuples
    """
    dt = params['dt']
    T = params['T']
    x = list(params['initial_state'])
    trajectory = []
    t = 0.0
    N = int(round(T / dt))

    for _ in range(N):
        tau = controller.get_control_output(x, t)
        tau = max(-plant.tau_max, min(plant.tau_max, tau))
        trajectory.append((t, x[0], x[1], x[2], x[3], tau))

        k1 = plant.forward_dynamics(x, tau)
        x1 = [x[i] + 0.5 * dt * k1[i] for i in range(4)]
        k2 = plant.forward_dynamics(x1, tau)
        x2 = [x[i] + 0.5 * dt * k2[i] for i in range(4)]
        k3 = plant.forward_dynamics(x2, tau)
        x3 = [x[i] + dt * k3[i] for i in range(4)]
        k4 = plant.forward_dynamics(x3, tau)

        x = [x[i] + (dt / 6.0) * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i])
             for i in range(4)]
        t += dt

        if any(abs(v) > 1e8 for v in x):
            break

    tau = controller.get_control_output(x, t)
    tau = max(-plant.tau_max, min(plant.tau_max, tau))
    trajectory.append((t, x[0], x[1], x[2], x[3], tau))
    return trajectory
