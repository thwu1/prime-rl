#!/usr/bin/env python3
"""Compute thermal rectification in a two-qubit system using HEOM."""

import json
import os

import numpy as np
import qutip as qt
from qutip.core.environment import (
    CFExponent,
    DrudeLorentzEnvironment,
    system_terminator,
)
from qutip.solver.heom import HEOMSolver


# ---------------------------------------------------------------------------
# Physics helpers
# ---------------------------------------------------------------------------

def build_hamiltonian(epsilon, J12):
    """Build the two-qubit system Hamiltonian.

    H_S = eps/2 (sz1 + I)xI + Ix eps/2 (sz2 + I) + J12 (s+1 s-2 + s-1 s+2)
    """
    H1 = epsilon / 2 * qt.tensor(qt.sigmaz() + qt.identity(2), qt.identity(2))
    H2 = epsilon / 2 * qt.tensor(qt.identity(2), qt.sigmaz() + qt.identity(2))
    H12 = J12 * (
        qt.tensor(qt.sigmap(), qt.sigmam())
        + qt.tensor(qt.sigmam(), qt.sigmap())
    )
    return H1 + H2 + H12


def bath_heat_current(bath_tag, ado_state, hamiltonian, coupling_op, delta=0):
    """Bath heat current j_B^K = d/dt <H_B^K> from level-1 ADOs.

    Formula from Kato & Tanimura, J. Chem. Phys. 145, 224105 (2016).
    """
    l1_labels = ado_state.filter(level=1, tags=[bath_tag])
    a_op = 1j * (hamiltonian * coupling_op - coupling_op * hamiltonian)

    result = 0
    cI0 = 0
    for label in l1_labels:
        [exp] = ado_state.exps(label)
        result += exp.vk * (coupling_op * ado_state.extract(label)).tr()

        if exp.type == CFExponent.types["I"]:
            cI0 += exp.ck
        elif exp.type == CFExponent.types["RI"]:
            cI0 += exp.ck2

    result -= 2 * cI0 * (coupling_op * coupling_op * ado_state.rho).tr()

    if delta != 0:
        result -= (
            1j
            * delta
            * ((a_op * coupling_op - coupling_op * a_op) * ado_state.rho).tr()
        )
    return result


def compute_steady_currents(epsilon, J12, gamma, T1, T2, lam1, lam2, Nk, NC):
    """Compute steady-state bath heat currents j_B^1, j_B^2 via HEOM."""
    H = build_hamiltonian(epsilon, J12)

    # System coupling operators
    Q1 = qt.tensor(qt.sigmax(), qt.identity(2))
    Q2 = qt.tensor(qt.identity(2), qt.sigmax())

    # Bath 1 (coupled to qubit 1)
    env1 = DrudeLorentzEnvironment(lam=lam1, gamma=gamma, T=T1, tag="bath1")
    env1_approx, delta1 = env1.approximate(
        "pade", Nk=Nk, compute_delta=True, tag="bath1"
    )

    # Bath 2 (coupled to qubit 2)
    env2 = DrudeLorentzEnvironment(lam=lam2, gamma=gamma, T=T2, tag="bath2")
    env2_approx, delta2 = env2.approximate(
        "pade", Nk=Nk, compute_delta=True, tag="bath2"
    )

    # Liouvillian with system terminator corrections
    Ltot = (
        qt.liouvillian(H)
        + system_terminator(Q1, delta1)
        + system_terminator(Q2, delta2)
    )

    options = {
        "nsteps": 15000,
        "store_states": True,
        "rtol": 1e-12,
        "atol": 1e-12,
        "method": "vern9",
    }

    solver = HEOMSolver(
        Ltot,
        [(env1_approx, Q1), (env2_approx, Q2)],
        max_depth=NC,
        options=options,
    )

    # Solve for steady state
    _, steady_ados = solver.steady_state()

    j1 = float(np.real(bath_heat_current("bath1", steady_ados, H, Q1, delta1)))
    j2 = float(np.real(bath_heat_current("bath2", steady_ados, H, Q2, delta2)))

    return j1, j2


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Load parameters
    with open("/app/system_params.json") as f:
        params = json.load(f)

    epsilon = params["epsilon"]
    J12 = params["J12"]
    gamma = params["gamma"]
    T_hot = params["T_hot"]
    T_cold = params["T_cold"]
    lam_base = params["lam_base"]
    asymmetry_ratios = params["asymmetry_ratios"]
    Nk = params["Nk"]
    NC = params["NC"]

    os.makedirs("/app/results", exist_ok=True)

    currents = {}
    rectification = {}
    conservation = {}

    for alpha in asymmetry_ratios:
        alpha_key = str(alpha)
        lam1 = lam_base
        lam2 = alpha * lam_base

        print(f"Computing alpha={alpha} (lam1={lam1}, lam2={lam2}) ...")

        # Forward bias: T1=T_hot, T2=T_cold
        j1_fwd, j2_fwd = compute_steady_currents(
            epsilon, J12, gamma, T_hot, T_cold, lam1, lam2, Nk, NC,
        )
        J_fwd = abs(j1_fwd)

        # Reverse bias: T1=T_cold, T2=T_hot
        j1_rev, j2_rev = compute_steady_currents(
            epsilon, J12, gamma, T_cold, T_hot, lam1, lam2, Nk, NC,
        )
        J_rev = abs(j1_rev)

        # Store through-current magnitudes
        currents[alpha_key] = {"j_forward": J_fwd, "j_reverse": J_rev}

        # Rectification coefficient
        max_j = max(J_fwd, J_rev)
        R = (J_fwd - J_rev) / max_j if max_j > 0 else 0.0
        rectification[alpha_key] = R

        # Energy conservation error
        def _rel_err(ja, jb):
            denom = max(abs(ja), abs(jb))
            return abs(ja + jb) / denom if denom > 0 else 0.0

        conservation[alpha_key] = {
            "forward": _rel_err(j1_fwd, j2_fwd),
            "reverse": _rel_err(j1_rev, j2_rev),
        }

        print(
            f"  J_fwd={J_fwd:.6e}, J_rev={J_rev:.6e}, R={R:.6f}, "
            f"cons_fwd={conservation[alpha_key]['forward']:.2e}, "
            f"cons_rev={conservation[alpha_key]['reverse']:.2e}"
        )

    # Write results
    with open("/app/results/steady_state_currents.json", "w") as f:
        json.dump(currents, f, indent=2)

    with open("/app/results/rectification.json", "w") as f:
        json.dump(rectification, f, indent=2)

    with open("/app/results/energy_conservation.json", "w") as f:
        json.dump(conservation, f, indent=2)

    print("\nResults written to /app/results/")


if __name__ == "__main__":
    main()
