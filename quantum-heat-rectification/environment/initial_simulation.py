#!/usr/bin/env python3
"""
Thermal transport simulation for a two-qubit system coupled to
Drude-Lorentz bosonic heat baths.

Approach: Local Lindblad master equation with jump operators derived from
individual qubit transition operators at the bare qubit frequency. Heat
currents computed from the local qubit energy change rate.
"""

import json
import os

import numpy as np
import qutip as qt


def build_hamiltonian(epsilon, J12):
    """Two-qubit Hamiltonian."""
    H1 = epsilon / 2 * qt.tensor(qt.sigmaz() + qt.identity(2), qt.identity(2))
    H2 = epsilon / 2 * qt.tensor(qt.identity(2), qt.sigmaz() + qt.identity(2))
    H12 = J12 * (
        qt.tensor(qt.sigmap(), qt.sigmam())
        + qt.tensor(qt.sigmam(), qt.sigmap())
    )
    return H1 + H2 + H12


def drude_lorentz_sd(omega, lam, gamma):
    """Drude-Lorentz spectral density J(omega) = 2*lam*gamma*omega/(omega^2+gamma^2)."""
    if abs(omega) < 1e-15:
        return 0.0
    return 2 * lam * gamma * abs(omega) / (omega ** 2 + gamma ** 2)


def bose_einstein(omega, T):
    """Bose-Einstein occupation number."""
    if T <= 0 or abs(omega) < 1e-15:
        return 0.0
    return 1.0 / (np.exp(abs(omega) / T) - 1.0)


def main():
    with open("/app/system_params.json") as f:
        params = json.load(f)

    epsilon = params["epsilon"]
    J12 = params["J12"]
    gamma = params["gamma"]
    T_hot = params["T_hot"]
    T_cold = params["T_cold"]
    lam_base = params["lam_base"]
    asymmetry_ratios = params["asymmetry_ratios"]

    H = build_hamiltonian(epsilon, J12)

    # Local qubit Hamiltonians (bare, without interaction)
    H_local_1 = epsilon / 2 * qt.tensor(
        qt.sigmaz() + qt.identity(2), qt.identity(2)
    )
    H_local_2 = epsilon / 2 * qt.tensor(
        qt.identity(2), qt.sigmaz() + qt.identity(2)
    )

    # Local qubit transition operators
    sm1 = qt.tensor(qt.sigmam(), qt.identity(2))
    sp1 = qt.tensor(qt.sigmap(), qt.identity(2))
    sm2 = qt.tensor(qt.identity(2), qt.sigmam())
    sp2 = qt.tensor(qt.identity(2), qt.sigmap())

    os.makedirs("/app/results", exist_ok=True)

    currents = {}
    rectification = {}
    conservation = {}

    for alpha in asymmetry_ratios:
        alpha_key = str(alpha)
        lam1 = lam_base
        lam2 = alpha * lam_base

        bias_results = {}

        for direction, T1, T2 in [
            ("forward", T_hot, T_cold),
            ("reverse", T_cold, T_hot),
        ]:
            # Spectral density evaluated at bare qubit frequency
            sd1 = drude_lorentz_sd(epsilon, lam1, gamma)
            sd2 = drude_lorentz_sd(epsilon, lam2, gamma)

            n1 = bose_einstein(epsilon, T1)
            n2 = bose_einstein(epsilon, T2)

            # Local Lindblad collapse operators
            c_ops_bath1 = [
                np.sqrt(sd1 * (n1 + 1)) * sm1,  # decay qubit 1
                np.sqrt(sd1 * n1) * sp1,          # excitation qubit 1
            ]
            c_ops_bath2 = [
                np.sqrt(sd2 * (n2 + 1)) * sm2,  # decay qubit 2
                np.sqrt(sd2 * n2) * sp2,          # excitation qubit 2
            ]

            c_ops = c_ops_bath1 + c_ops_bath2

            # Steady state of the full system
            rho_ss = qt.steadystate(H, c_ops)

            # Dissipator contribution from each bath
            def dissipator(ops, rho):
                result = 0 * rho
                for L in ops:
                    result += (
                        L * rho * L.dag()
                        - 0.5 * (L.dag() * L * rho + rho * L.dag() * L)
                    )
                return result

            D1_rho = dissipator(c_ops_bath1, rho_ss)
            D2_rho = dissipator(c_ops_bath2, rho_ss)

            # Heat current: rate of LOCAL qubit energy change from each bath
            j1 = float(np.real((H_local_1 * D1_rho).tr()))
            j2 = float(np.real((H_local_2 * D2_rho).tr()))

            bias_results[direction] = (j1, j2)

        j1_fwd, j2_fwd = bias_results["forward"]
        j1_rev, j2_rev = bias_results["reverse"]

        J_fwd = abs(j1_fwd)
        J_rev = abs(j1_rev)

        currents[alpha_key] = {"j_forward": J_fwd, "j_reverse": J_rev}

        max_j = max(J_fwd, J_rev)
        R = (J_fwd - J_rev) / max_j if max_j > 0 else 0.0
        rectification[alpha_key] = R

        denom_fwd = max(abs(j1_fwd), abs(j2_fwd))
        denom_rev = max(abs(j1_rev), abs(j2_rev))
        cons_fwd = abs(j1_fwd + j2_fwd) / denom_fwd if denom_fwd > 0 else 0.0
        cons_rev = abs(j1_rev + j2_rev) / denom_rev if denom_rev > 0 else 0.0
        conservation[alpha_key] = {"forward": cons_fwd, "reverse": cons_rev}

        print(f"alpha={alpha}: J_fwd={J_fwd:.6e}, J_rev={J_rev:.6e}, R={R:.4f}")
        print(f"  Energy conservation: fwd={cons_fwd:.4f}, rev={cons_rev:.4f}")

    for fname, data in [
        ("steady_state_currents.json", currents),
        ("rectification.json", rectification),
        ("energy_conservation.json", conservation),
    ]:
        with open(f"/app/results/{fname}", "w") as f:
            json.dump(data, f, indent=2)

    print("\nResults written to /app/results/")


if __name__ == "__main__":
    main()
