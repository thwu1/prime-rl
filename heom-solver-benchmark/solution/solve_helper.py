#!/usr/bin/env python3
"""
Compute steady-state properties of the spin-boson model using HEOM and
secular Lindblad, then write results to /app/results/.

"""

import csv
import os
import sys

import numpy as np
import qutip as qt
from qutip import (
    basis,
    expect,
    identity,
    liouvillian,
    sigmaz,
    sigmax,
    spost,
    spre,
    steadystate,
)

# -----------------------------------------------------------------------
# Physical parameters
# -----------------------------------------------------------------------
EPS = 0.5       # qubit splitting
DELTA = 1.0     # tunneling amplitude
GAMMA = 0.5     # bath cutoff frequency
T = 0.5         # temperature  (k_B = hbar = 1)
BETA = 1.0 / T
NK = 2          # Matsubara expansion terms
NC_DEFAULT = 5  # default hierarchy depth

LAM_VALUES = [0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
NC_SWEEP = [2, 3, 4, 5, 6, 7, 8]
LAM_CONV = 0.5  # coupling strength for convergence study

# -----------------------------------------------------------------------
# System Hamiltonian & coupling
# -----------------------------------------------------------------------
Hsys = 0.5 * EPS * sigmaz() + 0.5 * DELTA * sigmax()
Q = sigmaz()
P11 = basis(2, 0) * basis(2, 0).dag()

# -----------------------------------------------------------------------
# HEOM solver construction (multi-API)
# -----------------------------------------------------------------------

def _cot(x):
    return 1.0 / np.tan(x)


def _matsubara_exponents(lam):
    """Return Matsubara expansion coefficients for Drude-Lorentz."""
    cot_v = _cot(GAMMA * BETA / 2)
    ckAR = [lam * GAMMA * cot_v]
    vkAR = [GAMMA]
    for k in range(1, NK + 1):
        vk = 2 * np.pi * k * T
        ckAR.append(4 * lam * GAMMA * T * vk / (vk ** 2 - GAMMA ** 2))
        vkAR.append(vk)
    ckAI = [lam * GAMMA * (-1.0)]
    vkAI = [GAMMA]
    return ckAR, vkAR, ckAI, vkAI


def _terminator_delta(lam, ckAR, vkAR):
    """Ishizaki-Tanimura terminator correction factor."""
    cot_v = _cot(GAMMA * BETA / 2)
    delta = (2 * lam / (BETA * GAMMA)) - 1j * lam
    # subtract k=0 combined RI term
    delta -= lam * GAMMA * (-1j + cot_v) / GAMMA
    # subtract k>=1 real Matsubara terms
    for k in range(1, NK + 1):
        vk = 2 * np.pi * k * T
        delta -= (4 * lam * GAMMA * T * vk / (vk ** 2 - GAMMA ** 2)) / vk
    return delta


def _terminator_superop(delta):
    """Build the Lindblad-form terminator superoperator."""
    op = (
        -2 * spre(Q) * spost(Q.dag())
        + spre(Q.dag() * Q)
        + spost(Q.dag() * Q)
    )
    return -delta * op


def make_heom_solver(lam, NC):
    """Create an HEOM solver, trying multiple QuTiP API entry-points."""
    opts = {
        "nsteps": 15000,
        "store_states": True,
        "rtol": 1e-12,
        "atol": 1e-12,
    }

    # --- Approach 1: legacy HSolverDL ---------------------------------
    try:
        from qutip.solver.heom import HSolverDL
        return HSolverDL(
            Hsys, Q, lam, T, NC, NK, GAMMA,
            bnd_cut_approx=True, options=opts,
        )
    except Exception:
        pass

    # --- Approach 2: DrudeLorentzEnvironment (new v5 API) -------------
    try:
        from qutip.core.environment import (
            DrudeLorentzEnvironment,
            system_terminator,
        )
        from qutip.solver.heom import HEOMSolver

        env = DrudeLorentzEnvironment(lam=lam, gamma=GAMMA, T=T)
        env_approx, delta = env.approximate(
            "matsubara", Nk=NK, compute_delta=True,
        )
        Ltot = liouvillian(Hsys) + system_terminator(Q, delta)
        return HEOMSolver(Ltot, (env_approx, Q), NC, options=opts)
    except Exception:
        pass

    # --- Approach 3: manual Matsubara + terminator --------------------
    from qutip.solver.heom import HEOMSolver

    ckAR, vkAR, ckAI, vkAI = _matsubara_exponents(lam)
    delta = _terminator_delta(lam, ckAR, vkAR)
    Ltot = liouvillian(Hsys) + _terminator_superop(delta)

    try:
        from qutip.core.environment import ExponentialBosonicEnvironment
        env = ExponentialBosonicEnvironment(ckAR, vkAR, ckAI, vkAI)
        bath_arg = (env, Q)
    except ImportError:
        try:
            from qutip.solver.heom import BosonicBath
            bath_arg = BosonicBath(Q, ckAR, vkAR, ckAI, vkAI)
        except ImportError:
            raise RuntimeError(
                "Cannot create HEOM bath: no compatible QuTiP API found"
            )

    return HEOMSolver(Ltot, bath_arg, NC, options=opts)


# -----------------------------------------------------------------------
# HEOM steady state
# -----------------------------------------------------------------------

def heom_steady_state(lam, NC=NC_DEFAULT):
    """Return the HEOM steady-state density matrix."""
    solver = make_heom_solver(lam, NC)
    try:
        rho_ss, _ = solver.steady_state()
        return rho_ss
    except Exception:
        pass
    # fallback: time evolution to approximate steady state
    rho0 = identity(2) / 2
    tlist = np.linspace(0, 150, 750)
    result = solver.run(rho0, tlist)
    return result.states[-1]


# -----------------------------------------------------------------------
# Secular Lindblad steady state
# -----------------------------------------------------------------------

def lindblad_steady_state(lam):
    """Compute the secular Lindblad steady state."""
    evals, estates = Hsys.eigenstates()
    gap = evals[1] - evals[0]

    # matrix element |<ground|Q|excited>|^2
    Q_me = float(np.abs(Q.matrix_element(estates[0].dag(), estates[1])) ** 2)

    # Drude-Lorentz spectral density at gap
    J_gap = 2 * lam * GAMMA * gap / (GAMMA ** 2 + gap ** 2)

    # Bose-Einstein distribution
    n_th = 1.0 / (np.exp(gap / T) - 1.0)

    # golden-rule transition rates
    rate_down = Q_me * J_gap * (n_th + 1)   # |excited> -> |ground>
    rate_up = Q_me * J_gap * n_th            # |ground> -> |excited>

    c_ops = []
    if rate_down > 0:
        c_ops.append(np.sqrt(rate_down) * estates[0] * estates[1].dag())
    if rate_up > 0:
        c_ops.append(np.sqrt(rate_up) * estates[1] * estates[0].dag())

    return steadystate(Hsys, c_ops)


# -----------------------------------------------------------------------
# Trace distance
# -----------------------------------------------------------------------

def trace_distance(rho1, rho2):
    diff = (rho1 - rho2).full()
    eigvals = np.linalg.eigvalsh(diff)
    return 0.5 * float(np.sum(np.abs(eigvals)))


# -----------------------------------------------------------------------
# Main computation
# -----------------------------------------------------------------------

def main():
    os.makedirs("/app/results", exist_ok=True)

    pop_rows = []
    coh_rows = []
    dist_rows = []

    for lam in LAM_VALUES:
        print(f"lambda = {lam} ...", flush=True)
        rho_h = heom_steady_state(lam)
        rho_l = lindblad_steady_state(lam)

        p11_h = float(np.real(expect(P11, rho_h)))
        p11_l = float(np.real(expect(P11, rho_l)))

        coh_h = float(np.abs(rho_h.full()[0, 1]))
        coh_l = float(np.abs(rho_l.full()[0, 1]))

        td = trace_distance(rho_h, rho_l)

        pop_rows.append((lam, p11_h, p11_l))
        coh_rows.append((lam, coh_h, coh_l))
        dist_rows.append((lam, td))

    # --- write populations ---
    with open("/app/results/populations.csv", "w", newline="") as f:
        w = csv.writer(f)
        for row in pop_rows:
            w.writerow([f"{v:.10f}" for v in row])

    # --- write coherences ---
    with open("/app/results/coherences.csv", "w", newline="") as f:
        w = csv.writer(f)
        for row in coh_rows:
            w.writerow([f"{v:.10f}" for v in row])

    # --- write trace distances ---
    with open("/app/results/trace_distances.csv", "w", newline="") as f:
        w = csv.writer(f)
        for row in dist_rows:
            w.writerow([f"{v:.10f}" for v in row])

    # --- convergence sweep ---
    print("convergence sweep (lambda=0.5) ...", flush=True)
    conv_rows = []
    for nc in NC_SWEEP:
        print(f"  NC = {nc} ...", flush=True)
        rho = heom_steady_state(LAM_CONV, nc)
        p11 = float(np.real(expect(P11, rho)))
        conv_rows.append((nc, p11))

    with open("/app/results/convergence.csv", "w", newline="") as f:
        w = csv.writer(f)
        for nc, p11 in conv_rows:
            w.writerow([nc, f"{p11:.10f}"])

    print("Done.", flush=True)


if __name__ == "__main__":
    main()
