"""Benchmark: QMC lattice rules vs Monte Carlo for high-dimensional integration."""
import json
import os
import numpy as np
from config import DIMENSION, COEFFICIENTS, WEIGHTS, CONVERGENCE_PRIMES, N_SHIFTS, SEED
from test_function import exponential_integrand, exact_integral
from mc_integrator import mc_estimate
from cbc import construct_generating_vector
from lattice import shifted_lattice_estimate


def main():
    coeffs = np.array(COEFFICIENTS)
    I_exact = exact_integral(coeffs)
    func = lambda x: exponential_integrand(x, coeffs)

    print(f"Benchmark: QMC vs MC for {DIMENSION}-dimensional exponential integral")
    print(f"Exact integral: {I_exact:.10f}")
    print(f"Weights: gamma_j = 1/j^2")
    print()

    # Convergence study across increasing lattice sizes
    qmc_errors = []
    mc_errors = []
    all_z = []
    all_qmc = []
    all_mc = []

    for n in CONVERGENCE_PRIMES:
        print(f"n = {n}:")

        z = construct_generating_vector(n, DIMENSION, WEIGHTS)
        all_z.append(z)

        qmc_est = shifted_lattice_estimate(func, z, n, DIMENSION, N_SHIFTS, SEED)
        all_qmc.append(qmc_est)
        qmc_err = abs(qmc_est - I_exact)
        qmc_errors.append(qmc_err)

        mc_est = mc_estimate(func, DIMENSION, n * N_SHIFTS, SEED)
        all_mc.append(mc_est)
        mc_err = abs(mc_est - I_exact)
        mc_errors.append(mc_err)

        print(f"  QMC = {qmc_est:.8f}  err = {qmc_err:.2e}")
        print(f"  MC  = {mc_est:.8f}  err = {mc_err:.2e}")

    # Estimate convergence rates via log-log linear regression
    log_n = np.log(np.array(CONVERGENCE_PRIMES, dtype=float))
    log_qmc = np.log(np.maximum(np.array(qmc_errors), 1e-16))
    log_mc = np.log(np.maximum(np.array(mc_errors), 1e-16))

    qmc_rate = float(-np.polyfit(log_n, log_qmc, 1)[0])
    mc_rate = float(-np.polyfit(log_n, log_mc, 1)[0])

    # Use the largest lattice as the main result
    main_n = CONVERGENCE_PRIMES[-1]
    main_z = all_z[-1]
    main_qmc = all_qmc[-1]
    main_mc = all_mc[-1]

    # Save results
    os.makedirs("results", exist_ok=True)
    results = {
        "dimension": DIMENSION,
        "exact_integral": float(I_exact),
        "qmc_estimate": float(main_qmc),
        "qmc_error": float(abs(main_qmc - I_exact)),
        "mc_estimate": float(main_mc),
        "mc_error": float(abs(main_mc - I_exact)),
        "qmc_convergence_rate": qmc_rate,
        "mc_convergence_rate": mc_rate,
        "generating_vector": [int(x) for x in main_z],
        "n_points": main_n,
        "n_shifts": N_SHIFTS,
        "convergence": {
            "n_values": CONVERGENCE_PRIMES,
            "qmc_errors": [float(e) for e in qmc_errors],
            "mc_errors": [float(e) for e in mc_errors]
        }
    }

    with open("results/benchmark.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*50}")
    print(f"QMC estimate: {main_qmc:.10f}  (error: {abs(main_qmc - I_exact):.2e})")
    print(f"MC  estimate: {main_mc:.10f}  (error: {abs(main_mc - I_exact):.2e})")
    print(f"QMC convergence rate: {qmc_rate:.3f}")
    print(f"MC  convergence rate: {mc_rate:.3f}")
    print(f"Results saved to results/benchmark.json")


if __name__ == "__main__":
    main()
