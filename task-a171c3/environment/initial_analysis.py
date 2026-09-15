"""QPE analysis for Heisenberg spin chains using LCU walk operator approach.

This script computes error bounds and runs a validation QPE simulation
for the Heisenberg model using the LCU (Linear Combination of Unitaries)
walk operator method.
"""
import json
import os

import numpy as np

import qpe_toolbox.estimation as qpe
from qpe_toolbox.hamiltonian import do_dmrg, heisenberg_hamiltonian

os.makedirs("/app/initial_results", exist_ok=True)

# ---- 4-qubit Heisenberg model ----
H4 = heisenberg_hamiltonian(4)
E0_4, psi0_4 = do_dmrg(H4)
weights_4, lmb_4, L_4, mL_4 = qpe.get_lcu_weights(H4)

# Compute LCU-QPE error bounds for varying phase register sizes
error_bounds = {}
for m_ph in range(2, 9):
    # Phase discretization maps to energy precision
    delta_E = lmb_4 * 2 * np.pi / 2**m_ph
    error_bounds[str(m_ph)] = delta_E

# ---- 2-qubit validation simulation ----
H2 = heisenberg_hamiltonian(2)
E0_2, psi0_2 = do_dmrg(H2)
lmb_2 = sum(abs(P[0]) for P in H2.terms)

traces, theta = qpe.run_qpe_lcu_walk_operator(H2, psi0_2, 2)
# Recover energy from the walk operator eigenphase
energy_2 = lmb_2 * np.sin(2 * np.pi * theta)

# Determine minimum phase register size for target precision 0.8
min_m_08 = next(m for m in range(2, 9) if error_bounds[str(m)] < 0.8)

results = {
    "four_qubit": {
        "ground_energy_dmrg": float(E0_4),
        "lambda_norm": float(lmb_4),
        "n_lcu_terms": L_4,
        "n_auxiliary_qubits": mL_4,
        "lcu_error_bounds": {k: float(v) for k, v in error_bounds.items()},
        "min_phase_qubits_precision_0.8": min_m_08,
    },
    "two_qubit_validation": {
        "ground_energy_dmrg": float(E0_2),
        "lambda_norm": float(lmb_2),
        "theta": float(theta),
        "extracted_energy": float(energy_2),
        "energy_matches_dmrg": bool(abs(E0_2 - energy_2) < 0.1),
    },
    "method_evaluated": "lcu_walk_operator",
    "other_methods_evaluated": [],
    "notes": "Error bound: delta_E = lambda * 2pi / 2^m_ph. Energy: E = lambda * sin(2*pi*theta)",
}

with open("/app/initial_results/analysis.json", "w") as f:
    json.dump(results, f, indent=2)

print("Analysis complete. Results written to /app/initial_results/analysis.json")
