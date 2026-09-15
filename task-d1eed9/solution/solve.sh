#!/bin/bash

# Copy solution implementation into place
cp /solution/sp2_solution.py /app/sp2_solver.py

# Verify the solution by running the solver
python3 -c "
import sys
sys.path.insert(0, '/app')
import json
from hamiltonian import generate_hamiltonian
from sp2_solver import sparse_sp2, gershgorin_bounds, compute_comm_volume, optimal_partition

with open('/app/config.json') as f:
    cfg = json.load(f)

H = generate_hamiltonian(cfg['n_atoms'], seed=cfg['seed'],
                         n_chains=cfg['n_chains'],
                         chain_coupling=cfg['chain_coupling'])

print('=== Gershgorin Bounds ===')
emin, emax = gershgorin_bounds(H)
print(f'Eigenvalue range: [{emin:.4f}, {emax:.4f}]')

print()
print('=== Sparse SP2 Purification ===')
D, n_iter, idem_err = sparse_sp2(H, cfg['n_occupied'],
                                  tol=cfg['tolerance'],
                                  trunc_thresh=cfg['truncation_threshold'])
print(f'Converged in {n_iter} iterations')
print(f'Idempotency error: {idem_err:.2e}')
print(f'Trace(D): {D.diagonal().sum():.6f} (target: {cfg[\"n_occupied\"]})')
print(f'Density matrix nnz: {D.nnz} / {cfg[\"n_atoms\"]**2}')

print()
print('=== Communication Volume Analysis ===')
n = cfg['n_atoms']
nb = cfg['n_blocks']
uniform = [i * n // nb for i in range(nb)] + [n]
vol_uni = compute_comm_volume(H, uniform)
print(f'Uniform partition: {uniform}')
print(f'Uniform comm volume: {vol_uni}')

optimal = optimal_partition(H, nb)
vol_opt = compute_comm_volume(H, optimal)
print(f'Optimal partition: {optimal}')
print(f'Optimal comm volume: {vol_opt}')
print(f'Improvement: {(vol_uni - vol_opt) / vol_uni * 100:.1f}%')
"
