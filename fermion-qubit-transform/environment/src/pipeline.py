"""Main pipeline: load data, encode, analyze, write results."""
import json
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from data_loader import load_config, list_systems, load_system, to_spin_orbital_basis
from qubit_encoding import primary_encoding, secondary_encoding
from analysis import diagonalize, find_symmetry_reduction


def run():
    config = load_config()
    db_path = config["database_path"]
    convention = config.get("integral_convention", "physicist")
    output_path = config.get("output_path", "/app/results.json")

    systems = list_systems(db_path)
    print(f"Found {len(systems)} molecular systems")

    all_results = {}

    for name, desc, n_so, n_elec in systems:
        print(f"\n--- Processing {name} ---")
        print(f"  {desc}")
        print(f"  n_spatial_orbitals: {n_so}, n_electrons: {n_elec}, n_qubits: {2*n_so}")

        data = load_system(db_path, name, convention=convention)
        h_spin, g_spin, n_spin = to_spin_orbital_basis(data)
        nuc_rep = data["nuclear_repulsion_energy"]

        # Primary encoding
        print(f"  Computing primary encoding...")
        enc_a = primary_encoding(h_spin, g_spin, nuc_rep, n_spin)
        enc_a_terms = len(enc_a)
        print(f"    {enc_a_terms} Pauli terms")

        # Secondary encoding
        print(f"  Computing secondary encoding...")
        enc_b = None
        enc_b_terms = 0
        try:
            enc_b = secondary_encoding(h_spin, g_spin, nuc_rep, n_spin)
            enc_b_terms = len(enc_b)
            print(f"    {enc_b_terms} Pauli terms")
        except NotImplementedError as e:
            print(f"    ERROR: {e}")

        # Diagonalize
        print(f"  Diagonalizing...")
        eigs_a = diagonalize(enc_a, n_spin)
        ground_energy = float(eigs_a[0])
        print(f"    Ground state energy: {ground_energy:.10f}")

        spectral_match = False
        if enc_b is not None:
            eigs_b = diagonalize(enc_b, n_spin)
            spectral_match = bool(np.allclose(eigs_a, eigs_b, atol=1e-8))
            print(f"    Spectral match: {spectral_match}")

        # Symmetry reduction
        print(f"  Computing symmetry reduction...")
        n_sym = 0
        tapered_nq = n_spin
        tapered_energy = ground_energy
        try:
            sym_result = find_symmetry_reduction(enc_a, n_spin)
            n_sym = sym_result["n_symmetries"]
            tapered_nq = sym_result["reduced_n_qubits"]
            tapered_energy = sym_result["reduced_ground_energy"]
        except NotImplementedError as e:
            print(f"    ERROR: {e}")

        result = {
            "ground_state_energy": ground_energy,
            "n_qubits": n_spin,
            "encoding_a_num_terms": enc_a_terms,
            "encoding_b_num_terms": enc_b_terms,
            "eigenvalues_sorted": [float(x) for x in eigs_a],
            "spectral_match": spectral_match,
            "n_symmetries": n_sym,
            "tapered_n_qubits": tapered_nq,
            "tapered_ground_state_energy": float(tapered_energy),
        }
        all_results[name] = result

    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    run()
