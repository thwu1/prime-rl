"""
Analysis script for symplectic integrator comparison on the Kepler problem.

Runs convergence-order tests (Richardson extrapolation over multiple step sizes)
and long-term conservation analysis (energy and angular momentum over 50 orbits).

Produces /app/results.json.
"""
import numpy as np
import json
import sys

sys.path.insert(0, '/app')
from kepler import force, hamiltonian, angular_momentum, Q0, P0, H0, L0, PERIOD
from integrators import rk4_step, verlet_step, yoshida_compose, integrate


def convergence_test(step_fn, q0, p0, force_fn, T, step_counts):
    """
    Test convergence order by measuring phase-space error at t = T.

    Uses the periodicity of the Kepler orbit: the exact solution at t = N*T
    returns to the initial condition (q0, p0). Step counts are chosen so that
    dt = T / N divides the period exactly.

    Returns:
        errors: list of float, phase-space distance ||z(T) - z(0)||
        orders: list of float, estimated convergence orders from successive pairs
    """
    errors = []
    for N in step_counts:
        dt = T / N
        qs, ps = integrate(step_fn, q0, p0, dt, N, force_fn)
        q_final = qs[-1]
        p_final = ps[-1]
        err = np.sqrt(np.sum((q_final - q0)**2) + np.sum((p_final - p0)**2))
        errors.append(float(err))

    orders = []
    for i in range(1, len(errors)):
        if errors[i] > 1e-15 and errors[i - 1] > 1e-15:
            ratio = step_counts[i] / step_counts[i - 1]
            order = np.log(errors[i - 1] / errors[i]) / np.log(ratio)
            orders.append(float(round(order, 6)))
        else:
            orders.append(float('nan'))

    return errors, orders


def conservation_test(step_fn, q0, p0, force_fn, dt, T):
    """
    Test energy and angular momentum conservation over a long integration.

    Returns dict with max/final errors, and energy drift rate (linear fit slope).
    """
    num_steps = int(round(T / dt))
    qs, ps = integrate(step_fn, q0, p0, dt, num_steps, force_fn)

    H0_val = hamiltonian(q0, p0)
    L0_val = angular_momentum(q0, p0)

    energies = np.array([hamiltonian(qs[i], ps[i]) for i in range(len(qs))])
    momenta = np.array([angular_momentum(qs[i], ps[i]) for i in range(len(qs))])

    dE = energies - H0_val
    dL = momenta - L0_val

    # Linear fit for drift rate
    times = np.arange(len(dE)) * dt
    coeffs = np.polyfit(times, dE, 1)
    drift_rate = float(coeffs[0])

    return {
        "max_energy_error": float(np.max(np.abs(dE))),
        "max_momentum_error": float(np.max(np.abs(dL))),
        "final_energy_error": float(np.abs(dE[-1])),
        "final_momentum_error": float(np.abs(dL[-1])),
        "energy_drift_rate": drift_rate,
    }


def main():
    # Build higher-order integrators via Yoshida composition
    yoshida4_step = yoshida_compose(verlet_step, 2)
    yoshida6_step = yoshida_compose(yoshida4_step, 4)

    integrators = {
        "rk4": rk4_step,
        "verlet": verlet_step,
        "yoshida4": yoshida4_step,
        "yoshida6": yoshida6_step,
    }

    results = {}

    # --- Convergence test: one full orbital period ---
    step_counts = [64, 128, 256, 512, 1024]

    print("=== Convergence Tests ===")
    for name, step_fn in integrators.items():
        errors, orders = convergence_test(
            step_fn, Q0, P0, force, PERIOD, step_counts
        )
        results[f"{name}_convergence"] = {
            "step_counts": step_counts,
            "errors": errors,
            "orders": orders,
        }
        print(f"{name}: errors = {[f'{e:.3e}' for e in errors]}")
        print(f"{name}: orders = {[f'{o:.2f}' for o in orders]}")

    # --- Conservation test: 50 orbits ---
    dt_conservation = PERIOD / 128
    T_long = 50 * PERIOD

    print("\n=== Conservation Tests (50 orbits) ===")
    for name, step_fn in integrators.items():
        cons = conservation_test(step_fn, Q0, P0, force, dt_conservation, T_long)
        results[f"{name}_conservation"] = cons
        print(
            f"{name}: max|dE| = {cons['max_energy_error']:.3e}, "
            f"max|dL| = {cons['max_momentum_error']:.3e}, "
            f"drift  = {cons['energy_drift_rate']:.3e}"
        )

    # Write results
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
