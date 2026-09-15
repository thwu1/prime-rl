"""
Benchmark: convergence rates and conservation properties for methods A-E
on the Kepler two-body orbit problem.

Produces /app/results.json.
"""
import json
import numpy as np
import sys

sys.path.insert(0, '/app')
from physics import force, hamiltonian, angular_momentum, Q0, P0, H0, L0, PERIOD
from methods import method_a, method_b, method_c, method_d, method_e, integrate


def convergence_test(step_fn, q0, p0, force_fn, T, step_counts):
    """Measure phase-space error at t=T for decreasing step sizes.

    Uses the periodicity of the Kepler orbit: the exact solution at t=T
    returns to the initial condition, so ||z(T) - z(0)|| measures the
    global integration error.
    """
    errors = []
    for N in step_counts:
        dt = T / N
        qs, ps = integrate(step_fn, q0, p0, dt, N, force_fn)
        err = np.sqrt(np.sum((qs[-1] - q0)**2) + np.sum((ps[-1] - p0)**2))
        errors.append(float(err))

    orders = []
    for i in range(1, len(errors)):
        if errors[i] > 1e-15 and errors[i - 1] > 1e-15:
            order = np.log2(errors[i - 1] / errors[i])
            orders.append(float(round(order, 6)))
        else:
            orders.append(float('nan'))

    return errors, orders


def conservation_test(step_fn, q0, p0, force_fn, dt, T):
    """Measure energy and angular momentum conservation over a long
    integration of T time units."""
    num_steps = int(round(T / dt))
    qs, ps = integrate(step_fn, q0, p0, dt, num_steps, force_fn)

    H0_val = hamiltonian(q0, p0)
    L0_val = angular_momentum(q0, p0)

    energies = np.array([hamiltonian(qs[i], ps[i]) for i in range(len(qs))])
    momenta = np.array([angular_momentum(qs[i], ps[i]) for i in range(len(qs))])

    dE = energies - H0_val
    dL = momenta - L0_val

    times = np.arange(len(dE)) * dt
    coeffs = np.polyfit(times, dE, 1)

    return {
        "max_energy_error": float(np.max(np.abs(dE))),
        "max_momentum_error": float(np.max(np.abs(dL))),
        "final_energy_error": float(np.abs(dE[-1])),
        "final_momentum_error": float(np.abs(dL[-1])),
        "energy_drift_rate": float(coeffs[0]),
    }


def main():
    integrators = {
        "method_a": method_a,
        "method_b": method_b,
        "method_c": method_c,
        "method_d": method_d,
        "method_e": method_e,
    }

    results = {}

    step_counts = [50, 100, 250, 500, 1250]

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

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
