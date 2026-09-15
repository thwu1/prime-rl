#!/usr/bin/env python3
"""Corrected QPE analysis: diagnose bugs, fix, extend to multi-method comparison."""

import json
import os

import numpy as np
import quimb.tensor as qtn

import qpe_toolbox.estimation as qpe
from qpe_toolbox.circuit import count_gates_by_qb, make_circ
from qpe_toolbox.hamiltonian import do_dmrg, heisenberg_hamiltonian
from qpe_toolbox.tensor import kron_mps

os.makedirs("/app/results", exist_ok=True)

# ======================================================================
# 1. Spectrum: eigenvalue spectrum and DMRG ground-state energy
# ======================================================================
H4 = heisenberg_hamiltonian(4)
E0_4, psi0_4 = do_dmrg(H4)
eigenvalues_4 = sorted(np.linalg.eigvalsh(H4.to_dense()).tolist())

spectrum = {
    "n_qubits": 4,
    "n_terms": H4.n_terms,
    "eigenvalues": eigenvalues_4,
    "ground_energy_dmrg": float(E0_4),
}
with open("/app/results/spectrum.json", "w") as f:
    json.dump(spectrum, f, indent=2)

print(f"[1/6] Spectrum: E0 = {E0_4:.10f}, {len(eigenvalues_4)} eigenvalues")

# ======================================================================
# 2. LCU parameters and oracle verification
# ======================================================================
weights_4, lmb_4, L_4, mL_4 = qpe.get_lcu_weights(H4)

# Verify SELECT oracle: SELECT^2 = I (unitarity)
select_mpo = qpe.build_lcu_select_mpo(H4)
select_sq = select_mpo.apply(select_mpo)
select_sq.compress(cutoff=1e-18)
err_select = select_sq - qtn.MPO_identity(mL_4 + H4.n_qubits)
select_is_unitary = bool(abs(err_select.norm()) ** 2 < 1e-10)

# Verify reflection oracle: R_L^2 = I (involution)
R_L = qpe.build_lcu_reflection_mpo(H4)
rl_sq = R_L.apply(R_L)
err_rl = rl_sq - qtn.MPO_identity(mL_4 + H4.n_qubits)
reflection_is_involution = bool(abs(err_rl.norm()) ** 2 < 1e-10)

# SELECT energy ratio: <psi0|<L| SELECT |L>|psi0> = E0 / lambda
L_mps = qpe.build_lcu_prepare_state_mps(H4)
Lpsi_mps = kron_mps(L_mps, psi0_4)
select_gates = qpe.lcu_select_gates(H4)
circ = qtn.CircuitMPS(psi0=Lpsi_mps)
for gate in select_gates:
    circ.apply_gate(gate)
select_energy_ratio = float(np.real(Lpsi_mps.H @ circ.psi))

lcu_params = {
    "lambda_norm": float(lmb_4),
    "n_lcu_terms": L_4,
    "n_auxiliary_qubits": mL_4,
    "weights": [float(w) for w in weights_4],
    "select_is_unitary": select_is_unitary,
    "reflection_is_involution": reflection_is_involution,
    "select_energy_ratio": select_energy_ratio,
}
with open("/app/results/lcu_parameters.json", "w") as f:
    json.dump(lcu_params, f, indent=2)

print(f"[2/6] LCU params: lambda={lmb_4}, L={L_4}, mL={mL_4}, "
      f"SELECT unitary={select_is_unitary}, R_L involution={reflection_is_involution}")

# ======================================================================
# 3. Corrected error bounds for both methods
# ======================================================================
# Bug diagnosis:
#   The initial analysis used delta_E = lambda * 2*pi / 2^m_ph (simplified)
#   The correct LCU error bound is:
#     delta_E = lambda * sqrt(1 - (E0/lambda)^2) * 2*pi / 2^m_ph
#   This accounts for the non-linear arccos mapping between walk eigenphases
#   and energies.

corrected_bounds = {}
for m_ph in range(2, 9):
    key = str(m_ph)
    lcu_err = float(qpe.estimate_lcu_error(m_ph, E0_4, lmb_4))
    trotter_res = 2.0 / (2**m_ph)
    corrected_bounds[key] = {
        "lcu_error": lcu_err,
        "trotter_resolution": trotter_res,
    }

with open("/app/results/corrected_bounds.json", "w") as f:
    json.dump(corrected_bounds, f, indent=2)

print(f"[3/6] Corrected bounds computed for m_ph=2..8")

# ======================================================================
# 4. Gate counts for Trotter-QPE
# ======================================================================
n_phase_bits = 2
n_trotter_steps = 2
energy_target = E0_4 + 0.1
size_interval = 2

initial_circ = make_circ(n_phase_bits, psi0_4)
traces, _energy = qpe.qpe_energy(
    H4, initial_circ, n_trotter_steps, energy_target, size_interval
)
count = count_gates_by_qb(traces["gates_count"])
count["total_entangling"] = count["2qb"] + count["3+qb"]

with open("/app/results/gate_counts.json", "w") as f:
    json.dump(count, f, indent=2)

print(f"[4/6] Gate counts: {count}")

# ======================================================================
# 5. QPE validation on 2-qubit system (corrected energy extraction)
# ======================================================================
# Bug diagnosis:
#   The initial analysis used E = lambda * sin(2*pi*theta)
#   The correct formula is E = lambda * cos(2*pi*theta)
#   This follows from the walk operator eigenphase structure:
#     W|L>|psi_k> has eigenphases +/- arccos(E_k/lambda)

H2 = heisenberg_hamiltonian(2)
E0_2, psi0_2 = do_dmrg(H2)
lmb_2 = sum(abs(P[0]) for P in H2.terms)

traces_2, theta = qpe.run_qpe_lcu_walk_operator(H2, psi0_2, 2)
energy = float(qpe.get_energy_from_lcu_walk_phase(theta, lmb_2))
error_bound = float(qpe.estimate_lcu_error(2, E0_2, lmb_2))

# Handle edge case where error_bound is effectively zero
energy_matches = bool(abs(E0_2 - energy) <= error_bound + 1e-12)

validation = {
    "theta": float(theta),
    "energy": energy,
    "ground_energy": float(E0_2),
    "lambda_norm": float(lmb_2),
    "error_bound": error_bound,
    "energy_matches": energy_matches,
}
with open("/app/results/qpe_validation.json", "w") as f:
    json.dump(validation, f, indent=2)

print(f"[5/6] QPE validation: theta={theta}, E={energy:.6f}, "
      f"E0={E0_2:.6f}, matches={energy_matches}")

# ======================================================================
# 6. Recommendation: minimum phase qubits and method comparison
# ======================================================================
target_precision = 0.8

# LCU minimum phase register size for target precision
lcu_min = None
for m in range(2, 9):
    if qpe.estimate_lcu_error(m, E0_4, lmb_4) < target_precision:
        lcu_min = m
        break

# Trotter minimum phase register size (resolution = size_interval / 2^m)
trotter_min = None
for m in range(1, 9):
    if size_interval / (2**m) < target_precision:
        trotter_min = m
        break

recommendation = {
    "target_precision": target_precision,
    "lcu_min_phase_qubits": lcu_min,
    "trotter_min_phase_qubits": trotter_min,
    "recommended_method": "trotter",
    "justification": (
        f"For a target precision of {target_precision}, Trotter-QPE requires only "
        f"{trotter_min} phase qubits (resolution = size_interval/2^m = "
        f"{size_interval / 2**trotter_min:.4f}) compared to {lcu_min} for LCU-QPE "
        f"(error bound = {qpe.estimate_lcu_error(lcu_min, E0_4, lmb_4):.4f}). "
        f"The LCU error bound includes a spectral normalization factor "
        f"sqrt(1 - (E0/lambda)^2) that makes it less favorable for precision "
        f"targets where this factor significantly inflates the required phase "
        f"register size. However, LCU avoids Trotter error entirely and may be "
        f"preferable for applications requiring guaranteed precision without "
        f"tuning the number of Trotter steps."
    ),
}
with open("/app/results/recommendation.json", "w") as f:
    json.dump(recommendation, f, indent=2)

print(f"[6/6] Recommendation: LCU needs {lcu_min} qubits, "
      f"Trotter needs {trotter_min} qubits → {recommendation['recommended_method']}")
print("\nAll results written to /app/results/")
