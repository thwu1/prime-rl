#!/usr/bin/env python3
"""
QPE Resource and Oracle Analysis for Heisenberg Spin Chains.

Produces structured JSON output files analyzing Quantum Phase Estimation
approaches using both Trotter-Suzuki decomposition and LCU qubitization.
"""

import json
import os

import numpy as np
import quimb.tensor as qtn

import qpe_toolbox.estimation as qpe
from qpe_toolbox.circuit import count_gates_by_qb, make_circ
from qpe_toolbox.hamiltonian import do_dmrg, heisenberg_hamiltonian
from qpe_toolbox.tensor import kron_mps

os.makedirs("/app/results", exist_ok=True)

# ==========================================================================
# 1. Hamiltonian Spectrum (4-qubit Heisenberg)
# ==========================================================================
print("=== 1. Hamiltonian Spectrum ===")
n_qubits = 4
H = heisenberg_hamiltonian(n_qubits)
H_dense = H.to_dense()
eigenvalues = sorted([float(e) for e in np.linalg.eigvalsh(H_dense)])
E0_dmrg, psi0_mps = do_dmrg(H)

with open("/app/results/hamiltonian_spectrum.json", "w") as f:
    json.dump({
        "n_qubits": n_qubits,
        "n_terms": H.n_terms,
        "eigenvalues": eigenvalues,
        "ground_energy_dmrg": float(E0_dmrg),
    }, f, indent=2)
print(f"  n_qubits={n_qubits}, n_terms={H.n_terms}, E0_dmrg={E0_dmrg:.10f}")

# ==========================================================================
# 2. LCU Analysis: Decomposition + Oracle Verification
# ==========================================================================
print("\n=== 2. LCU Analysis ===")
weights, lmb, L, m_L = qpe.get_lcu_weights(H)
print(f"  lambda={lmb:.4f}, L={L}, m_L={m_L}")

# --- Verify SELECT^2 = I ---
select_mpo = qpe.build_lcu_select_mpo(H)
Id_check = select_mpo.apply(select_mpo)
Id_check.compress(cutoff=1e-18)
err_select = Id_check - qtn.MPO_identity(m_L + n_qubits)
select_is_unitary = bool(abs(err_select.norm()) ** 2 < 1e-10)
print(f"  SELECT is unitary: {select_is_unitary}")

# --- Verify R_L^2 = I ---
R_L = qpe.build_lcu_reflection_mpo(H)
Id_refl = R_L.apply(R_L)
err_refl = Id_refl - qtn.MPO_identity(m_L + n_qubits)
reflection_is_involution = bool(abs(err_refl.norm()) ** 2 < 1e-10)
print(f"  R_L is involution: {reflection_is_involution}")

# --- Compute <psi0|<L| SELECT |L>|psi0> = E0 / lambda ---
L_mps = qpe.build_lcu_prepare_state_mps(H)
Lpsi_mps = kron_mps(L_mps, psi0_mps)
select_gates = qpe.lcu_select_gates(H)
circ = qtn.CircuitMPS(psi0=Lpsi_mps)
for gate in select_gates:
    circ.apply_gate(gate)
select_energy_ratio = float(np.real(Lpsi_mps.H @ circ.psi))
print(f"  SELECT energy ratio: {select_energy_ratio:.10f} (E0/lambda={E0_dmrg/lmb:.10f})")

with open("/app/results/lcu_analysis.json", "w") as f:
    json.dump({
        "lambda_norm": float(lmb),
        "n_lcu_terms": int(L),
        "n_auxiliary_qubits": int(m_L),
        "weights": [float(w) for w in weights],
        "select_is_unitary": select_is_unitary,
        "reflection_is_involution": reflection_is_involution,
        "select_energy_ratio": select_energy_ratio,
    }, f, indent=2)

# ==========================================================================
# 3. Error Bounds for varying phase qubits
# ==========================================================================
print("\n=== 3. Error Bounds ===")
error_data = {}
size_interval = 2.0
for m_ph in [2, 3, 4, 5, 6, 7, 8]:
    lcu_err = float(qpe.estimate_lcu_error(m_ph, E0_dmrg, lmb))
    trotter_res = size_interval / (2**m_ph)
    error_data[str(m_ph)] = {
        "lcu_error": lcu_err,
        "trotter_resolution": trotter_res,
    }
    print(f"  m_ph={m_ph}: LCU err={lcu_err:.6f}, Trotter res={trotter_res:.6f}")

with open("/app/results/error_bounds.json", "w") as f:
    json.dump(error_data, f, indent=2)

# ==========================================================================
# 4. Gate Counts: Trotter-QPE on Heisenberg-4
# ==========================================================================
print("\n=== 4. Gate Counts ===")
n_phase_bits = 2
n_trotter_steps = 2
energy_target = E0_dmrg + 0.1

initial_circ = make_circ(n_phase_bits, psi0_mps)
traces, _energy = qpe.qpe_energy(
    H, initial_circ, n_trotter_steps, energy_target, size_interval
)
count = count_gates_by_qb(traces["gates_count"])
print(f"  Gate counts: {count}")

with open("/app/results/gate_counts.json", "w") as f:
    json.dump({
        "1qb": count["1qb"],
        "2qb": count["2qb"],
        "3+qb": count["3+qb"],
        "total_entangling": count["2qb"] + count["3+qb"],
    }, f, indent=2)

# ==========================================================================
# 5. QPE Simulation: LCU-QPE on Heisenberg-2
# ==========================================================================
print("\n=== 5. LCU-QPE Simulation ===")
H2 = heisenberg_hamiltonian(2)
E0_h2, psi0_h2 = do_dmrg(H2)
lmb_h2 = sum([abs(P[0]) for P in H2.terms])

m_ph = 2
_traces, theta = qpe.run_qpe_lcu_walk_operator(H2, psi0_h2, m_ph)
energy = float(qpe.get_energy_from_lcu_walk_phase(theta, lmb_h2))
error_bound = float(qpe.estimate_lcu_error(m_ph, E0_h2, lmb_h2))
energy_matches = bool(abs(E0_h2 - energy) < error_bound)

print(f"  theta={theta:.10f}, energy={energy:.10f}")
print(f"  E0={E0_h2:.10f}, error_bound={error_bound:.2e}")
print(f"  energy_matches={energy_matches}")

with open("/app/results/qpe_simulation.json", "w") as f:
    json.dump({
        "theta": float(theta),
        "energy": energy,
        "ground_energy": float(E0_h2),
        "lambda_norm": float(lmb_h2),
        "error_bound": error_bound,
        "energy_matches": energy_matches,
    }, f, indent=2)

print("\nAnalysis complete. Results written to /app/results/")
