"""Generate synthetic Lotka-Volterra predator-prey data using RK4 integration."""
import numpy as np
import json
import os


def lotka_volterra(t, z, alpha, beta, gamma, delta):
    """Standard Lotka-Volterra ODE: du/dt=(alpha-beta*v)*u, dv/dt=(-gamma+delta*u)*v."""
    u, v = z
    du_dt = (alpha - beta * v) * u
    dv_dt = (-gamma + delta * u) * v
    return np.array([du_dt, dv_dt])


def rk4_integrate(f, z0, t_eval, args, dt_substep=0.001):
    """Integrate ODE using 4th-order Runge-Kutta with fine substeps."""
    z = np.array(z0, dtype=float)
    trajectory = [z.copy()]
    for i in range(len(t_eval) - 1):
        t_start = t_eval[i]
        t_end = t_eval[i + 1]
        n_steps = max(1, int(np.ceil((t_end - t_start) / dt_substep)))
        dt = (t_end - t_start) / n_steps
        t = t_start
        for _ in range(n_steps):
            k1 = f(t, z, *args)
            k2 = f(t + dt / 2, z + dt / 2 * k1, *args)
            k3 = f(t + dt / 2, z + dt / 2 * k2, *args)
            k4 = f(t + dt, z + dt * k3, *args)
            z = z + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
            t += dt
        trajectory.append(z.copy())
    return np.array(trajectory)


def main():
    alpha, beta, gamma, delta = 1.0, 0.1, 1.5, 0.075
    z0 = [25.0, 8.0]
    sigma = [0.15, 0.15]

    t_eval = np.arange(0, 11, dtype=float)  # 11 time points: 0..10

    trajectory = rk4_integrate(
        lotka_volterra, z0, t_eval, (alpha, beta, gamma, delta)
    )

    np.random.seed(123)
    u_obs = trajectory[:, 0] * np.exp(np.random.normal(0, sigma[0], len(t_eval)))
    v_obs = trajectory[:, 1] * np.exp(np.random.normal(0, sigma[1], len(t_eval)))

    os.makedirs("/app", exist_ok=True)
    data = np.column_stack([t_eval, u_obs, v_obs])
    np.savetxt(
        "/app/data.csv", data, delimiter=",",
        header="time,u,v", comments="", fmt="%.6f"
    )

    ground_truth = {
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "delta": delta,
        "u0": z0[0],
        "v0": z0[1],
        "sigma_u": sigma[0],
        "sigma_v": sigma[1],
    }
    with open("/app/ground_truth.json", "w") as f:
        json.dump(ground_truth, f, indent=2)

    print("Data generated successfully.")
    print(f"Time points: {len(t_eval)}")
    print(f"u range: [{u_obs.min():.2f}, {u_obs.max():.2f}]")
    print(f"v range: [{v_obs.min():.2f}, {v_obs.max():.2f}]")


if __name__ == "__main__":
    main()
