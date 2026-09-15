#!/usr/bin/env python3
"""
Solve quantum heat transport: two coupled qubits, two Drude-Lorentz
bosonic heat baths at different temperatures.  Compute steady-state bath
heat currents for a range of system-bath coupling strengths.

"""

import json
import numpy as np
import qutip as qt
from qutip.core.environment import (
    CFExponent, DrudeLorentzEnvironment, system_terminator,
)
from qutip.solver.heom import HEOMSolver

# ── Parameters (must match instruction) ─────────────────────────────────────

EPSILON = 1.0
J12 = 0.05
GAMMA = 3.0
T_HOT = 2.5
T_COLD = 1.5
NK = 1
NC = 7
LAMBDAS = [0.005, 0.0125, 0.025, 0.05, 0.1, 0.2]

# ── System Hamiltonian ──────────────────────────────────────────────────────

H1 = (EPSILON / 2) * qt.tensor(qt.sigmaz() + qt.identity(2), qt.identity(2))
H2 = (EPSILON / 2) * qt.tensor(qt.identity(2), qt.sigmaz() + qt.identity(2))
H12 = J12 * (
    qt.tensor(qt.sigmap(), qt.sigmam())
    + qt.tensor(qt.sigmam(), qt.sigmap())
)
H_S = H1 + H2 + H12

# ── Coupling operators ──────────────────────────────────────────────────────

Q1 = qt.tensor(qt.sigmax(), qt.identity(2))
Q2 = qt.tensor(qt.identity(2), qt.sigmax())

# ── Observable ──────────────────────────────────────────────────────────────

SIGMA_Z1 = qt.tensor(qt.sigmaz(), qt.identity(2))


# ── Bath heat current from ADOs ─────────────────────────────────────────────

def bath_heat_current(bath_tag, ado_state, H, Q, delta=0):
    """
    Compute j_B^K = d/dt <H_B^K> using level-1 ADOs.

    j_B^K = sum_{n in L1,K} nu_n tr(Q rho_n)
            - 2 C_I^K(0) tr(Q^2 rho)
            + Gamma_T^K tr([[H, Q], Q] rho)
    """
    l1_labels = ado_state.filter(level=1, tags=[bath_tag])
    a_op = 1j * (H * Q - Q * H)       # i[H, Q]

    result = 0.0
    cI0 = 0.0                          # Im C^K(t=0)
    for label in l1_labels:
        [exp] = ado_state.exps(label)
        result += exp.vk * (Q * ado_state.extract(label)).tr()

        if exp.type == CFExponent.types["I"]:
            cI0 += exp.ck
        elif exp.type == CFExponent.types["RI"]:
            cI0 += exp.ck2

    result -= 2 * cI0 * (Q * Q * ado_state.rho).tr()

    if delta != 0:
        result -= (
            1j * delta
            * ((a_op * Q - Q * a_op) * ado_state.rho).tr()
        )
    return result


# ── Steady-state computation for a given lambda ─────────────────────────────

def compute_steady_state(lam):
    """Return (ados, j_B1, j_B2) for coupling strength lam."""
    env1 = DrudeLorentzEnvironment(
        lam=lam, gamma=GAMMA, T=T_HOT, tag="bath1",
    )
    env2 = DrudeLorentzEnvironment(
        lam=lam, gamma=GAMMA, T=T_COLD, tag="bath2",
    )

    ea1, d1 = env1.approx_by_pade(Nk=NK, compute_delta=True, tag="bath1")
    ea2, d2 = env2.approx_by_pade(Nk=NK, compute_delta=True, tag="bath2")

    solver = HEOMSolver(
        qt.liouvillian(H_S)
        + system_terminator(Q1, d1)
        + system_terminator(Q2, d2),
        [(ea1, Q1), (ea2, Q2)],
        max_depth=NC,
    )

    _, ados = solver.steady_state()

    j1 = bath_heat_current("bath1", ados, H_S, Q1, d1)
    j2 = bath_heat_current("bath2", ados, H_S, Q2, d2)
    return ados, j1, j2


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    out = {
        "steady_state_sigma_z1": None,
        "heat_currents": [],
        "peak_lambda": None,
        "peak_current_abs": 0.0,
        "energy_conservation_error": None,
    }

    for lam in LAMBDAS:
        print(f"lambda = {lam} ...", flush=True)
        ados, j1, j2 = compute_steady_state(lam)
        j1r = float(np.real(j1))
        j2r = float(np.real(j2))

        out["heat_currents"].append({
            "lambda": lam,
            "j_B1_real": j1r,
            "j_B2_real": j2r,
        })

        if abs(j1r) > out["peak_current_abs"]:
            out["peak_current_abs"] = abs(j1r)
            out["peak_lambda"] = lam

        if lam == 0.025:
            sz1 = float(np.real((SIGMA_Z1 * ados.rho).tr()))
            out["steady_state_sigma_z1"] = sz1
            denom = abs(j1r) if abs(j1r) > 0 else 1e-30
            out["energy_conservation_error"] = abs(j1r + j2r) / denom

    with open("/app/results.json", "w") as f:
        json.dump(out, f, indent=2)

    print("Done.  Results written to /app/results.json")
    print(json.dumps(out, indent=2))
