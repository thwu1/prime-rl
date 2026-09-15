#!/usr/bin/env python3
"""
Quantum error-mitigated potential energy surface for H2/STO-3G.

Constructs the Jordan-Wigner qubit Hamiltonian from PySCF molecular integrals,
decomposes into Pauli terms, computes exact ground states, simulates
Pauli-weight-dependent depolarizing noise, and applies Zero Noise Extrapolation
via Richardson polynomial extrapolation.
"""

import numpy as np
import json
import itertools
import warnings
import os

warnings.filterwarnings('ignore')

from pyscf import gto, scf


# ---------------------------------------------------------------------------
# Jordan-Wigner fermionic operators
# ---------------------------------------------------------------------------

def build_jw_operators(n_qubits):
    """Build creation and annihilation operator matrices in the JW basis."""
    dim = 2 ** n_qubits
    a_dag = []
    a_ann = []
    for j in range(n_qubits):
        ann = np.zeros((dim, dim))
        for s in range(dim):
            if (s >> j) & 1:
                ns = s ^ (1 << j)
                parity = bin(s & ((1 << j) - 1)).count('1')
                ann[ns, s] = (-1) ** parity
        a_ann.append(ann)
        a_dag.append(ann.T.copy())
    return a_dag, a_ann


# ---------------------------------------------------------------------------
# Integral handling
# ---------------------------------------------------------------------------

def spatial_to_spin(h1, eri, n_sp):
    """Convert spatial-MO integrals to spin-orbital integrals."""
    n = 2 * n_sp
    h1s = np.zeros((n, n))
    gs = np.zeros((n, n, n, n))

    for i in range(n_sp):
        for j in range(n_sp):
            h1s[2 * i,     2 * j]     = h1[i, j]
            h1s[2 * i + 1, 2 * j + 1] = h1[i, j]

    for p in range(n_sp):
        for q in range(n_sp):
            for r in range(n_sp):
                for s in range(n_sp):
                    v = eri[p, r, q, s]
                    gs[2*p,   2*q,   2*r,   2*s]   = v
                    gs[2*p+1, 2*q+1, 2*r+1, 2*s+1] = v
                    gs[2*p,   2*q+1, 2*r,   2*s+1] = v
                    gs[2*p+1, 2*q,   2*r+1, 2*s]   = v

    return h1s, gs


def compute_integrals(bond_length):
    """Run RHF on H2/STO-3G and return MO integrals + nuclear repulsion."""
    mol = gto.M(
        atom=f'H 0 0 0; H 0 0 {bond_length}',
        basis='sto-3g', charge=0, spin=0, verbose=0,
    )
    mf = scf.RHF(mol)
    mf.kernel()

    C = mf.mo_coeff
    n_ao = C.shape[1]

    h1_mo = C.T @ mf.get_hcore() @ C

    eri_ao = mol.intor('int2e').reshape(n_ao, n_ao, n_ao, n_ao)
    eri_mo = np.einsum('pi,qj,pqrs,rk,sl->ijkl', C, C, eri_ao, C, C)

    return h1_mo, eri_mo, mol.energy_nuc(), n_ao


# ---------------------------------------------------------------------------
# Qubit Hamiltonian
# ---------------------------------------------------------------------------

def build_qubit_hamiltonian(h1s, gs, e_nuc, nq):
    """Build the 2^nq x 2^nq qubit Hamiltonian matrix."""
    a_dag, a_ann = build_jw_operators(nq)
    dim = 2 ** nq
    H = np.eye(dim) * e_nuc

    for p in range(nq):
        for q in range(nq):
            c = h1s[p, q]
            if abs(c) > 1e-14:
                H += c * (a_dag[p] @ a_ann[q])

    for p in range(nq):
        for q in range(nq):
            for r in range(nq):
                for s in range(nq):
                    c = gs[p, q, r, s]
                    if abs(c) > 1e-14:
                        H += 0.5 * c * (a_dag[p] @ a_dag[q] @ a_ann[s] @ a_ann[r])

    return H


# ---------------------------------------------------------------------------
# Pauli decomposition
# ---------------------------------------------------------------------------

_PAULIS = [
    np.eye(2, dtype=complex),
    np.array([[0, 1], [1, 0]], dtype=complex),
    np.array([[0, -1j], [1j, 0]], dtype=complex),
    np.array([[1, 0], [0, -1]], dtype=complex),
]


def pauli_decompose(H, nq):
    """Decompose H into Pauli basis: H = sum_i c_i P_i."""
    dim = 2 ** nq
    Hc = H.astype(complex)
    terms = []
    for idx in itertools.product(range(4), repeat=nq):
        P = _PAULIS[idx[0]]
        for k in range(1, nq):
            P = np.kron(P, _PAULIS[idx[k]])
        c = (np.trace(P @ Hc) / dim).real
        if abs(c) > 1e-12:
            w = sum(1 for x in idx if x != 0)
            terms.append((c, w, idx))
    return terms


def pauli_expectations(terms, psi, nq):
    """Compute <psi|P_i|psi> for each Pauli term."""
    psi_c = psi.astype(complex)
    exps = []
    for _, _, idx in terms:
        P = _PAULIS[idx[0]]
        for k in range(1, nq):
            P = np.kron(P, _PAULIS[idx[k]])
        ev = (psi_c.conj() @ P @ psi_c).real
        exps.append(ev)
    return exps


# ---------------------------------------------------------------------------
# Noise model and ZNE
# ---------------------------------------------------------------------------

def noisy_energy(terms, exps, noise_rate):
    """Pauli-weight-dependent depolarizing noise on expectation values."""
    lam = 1.0 - 4.0 * noise_rate / 3.0
    E = 0.0
    for (c, w, _), ev in zip(terms, exps):
        atten = lam ** w if w > 0 else 1.0
        E += c * atten * ev
    return E


def richardson_extrapolate(scale_factors, energies):
    """Polynomial Richardson extrapolation to zero noise."""
    sf = np.array(scale_factors, dtype=float)
    en = np.array(energies, dtype=float)
    deg = len(sf) - 1
    coeffs = np.polyfit(sf, en, deg)
    return float(np.polyval(coeffs, 0.0))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_bond_length(r, nq):
    """Full pipeline for one bond length."""
    h1_mo, eri_mo, e_nuc, n_sp = compute_integrals(r)
    h1s, gs = spatial_to_spin(h1_mo, eri_mo, n_sp)
    H = build_qubit_hamiltonian(h1s, gs, e_nuc, nq)

    evals, evecs = np.linalg.eigh(H)
    exact_e = float(evals[0])
    psi = evecs[:, 0]
    trace_e = float(np.trace(H) / (2 ** nq))

    terms = pauli_decompose(H, nq)
    exps = pauli_expectations(terms, psi, nq)

    return exact_e, trace_e, terms, exps


def main():
    cfg_path = '/opt/task/config.json'
    with open(cfg_path) as f:
        cfg = json.load(f)

    bl_lo, bl_hi = cfg['bond_length_range']
    n_bl = cfg['num_bond_lengths']
    base_p = cfg['noise_base_rate']

    bond_lengths = np.linspace(bl_lo, bl_hi, n_bl).tolist()
    noise_scale_factors = [1, 2, 3, 4, 5]

    # Derive number of qubits from molecule/basis
    _, _, _, n_sp = compute_integrals(bond_lengths[0])
    nq = 2 * n_sp

    exact_energies = []
    trace_energies = []
    noisy_energies = []
    zne_energies = []

    for i, r in enumerate(bond_lengths):
        exact_e, trace_e, terms, exps = process_bond_length(r, nq)
        exact_energies.append(exact_e)
        trace_energies.append(trace_e)

        ne = noisy_energy(terms, exps, base_p)
        noisy_energies.append(ne)

        scaled = [noisy_energy(terms, exps, c * base_p) for c in noise_scale_factors]
        ze = richardson_extrapolate(noise_scale_factors, scaled)
        zne_energies.append(ze)

        print(f"  R={r:.4f} A  exact={exact_e:.6f}  noisy={ne:.6f}  zne={ze:.6f}")

    min_idx = int(np.argmin(exact_energies))
    eq_bl = bond_lengths[min_idx]
    eq_e = exact_energies[min_idx]
    diss_e = exact_energies[-1] - eq_e

    results = {
        'bond_lengths': bond_lengths,
        'exact_energies': exact_energies,
        'noisy_energies': noisy_energies,
        'zne_energies': zne_energies,
        'trace_energies': trace_energies,
        'equilibrium_bond_length': eq_bl,
        'equilibrium_energy': eq_e,
        'dissociation_energy': diss_e,
        'noise_parameters': {
            'base_noise_rate': base_p,
            'noise_scale_factors': noise_scale_factors,
        },
    }

    os.makedirs('/app', exist_ok=True)
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nEquilibrium: R = {eq_bl:.4f} A, E = {eq_e:.6f} Ha")
    print(f"Dissociation energy: {diss_e:.6f} Ha")
    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
