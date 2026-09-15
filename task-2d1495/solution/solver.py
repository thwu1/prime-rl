#!/usr/bin/env python3

"""
Reference solution for the pipeline recovery and low-rank approximation task.

Investigation approach (multi-tool forensics):

1. sqlite3 /app/pipeline/pipeline.db
   - .tables -> shows: matrix_registry, pipeline_config, run_log
   - SELECT * FROM pipeline_config; -> gets tolerance=0.01, budget=60
   - SELECT * FROM matrix_registry; -> shows 5 entries (alpha..zeta)
   - SELECT message, details FROM run_log WHERE level='ERROR';
     -> details JSON shows byte mismatch for mat_gamma
   - SELECT json_extract(details,'$.actual_bytes') FROM run_log WHERE level='ERROR';
     -> 240000 vs expected 480000

2. h5ls /app/pipeline/data/mat_alpha.h5
   -> shows: matrix  Dataset {500, 200}  (confirms shape/dtype)
   h5ls /app/pipeline/data/mat_beta.h5
   -> shows: matrix  Dataset {300, 300}  (confirms shape/dtype)

3. ls -la /app/pipeline/data/
   -> mat_gamma.dat: 240000 bytes; 240000 / (400*150) = 4 -> float32 not float64
   -> mat_delta.dat: 500000 bytes; 500000/8 = 62500; 62500/250 = 250 cols, not 200
   -> mat_epsilon.dat: 640000 bytes; 640000/8 = 80000 = 200*400 (per NOTES.txt)
   -> no mat_zeta.dat file

4. cat /app/pipeline/NOTES.txt
   -> mat_epsilon is 200x400 float64, not in registry
   -> mat_gamma was re-exported as float32

Discoveries:
- mat_gamma: registry dtype float64 -> actual float32
- mat_delta: registry cols 200 -> actual 250
- mat_epsilon: file exists, not in registry (200x400 float64)
- mat_zeta: in registry, no backing file -> skip
"""

import numpy as np
import h5py
import json
import os

# Corrected matrix specifications (discovered through investigation)
SPECS = {
    'mat_alpha':   {'shape': (500, 200), 'dtype': 'float64', 'format': 'hdf5'},
    'mat_beta':    {'shape': (300, 300), 'dtype': 'float64', 'format': 'hdf5'},
    'mat_gamma':   {'shape': (400, 150), 'dtype': 'float32', 'format': 'raw'},
    'mat_delta':   {'shape': (250, 250), 'dtype': 'float64', 'format': 'raw'},
    'mat_epsilon': {'shape': (200, 400), 'dtype': 'float64', 'format': 'raw'},
}

RELATIVE_TOLERANCE = 0.01
RANK_BUDGET = 60


def load_matrix(name, spec):
    """Load matrix from HDF5 or raw binary, promote to float64."""
    data_dir = '/app/pipeline/data'
    if spec['format'] == 'hdf5':
        path = os.path.join(data_dir, '{}.h5'.format(name))
        with h5py.File(path, 'r') as f:
            A = f['matrix'][:]
    else:
        path = os.path.join(data_dir, '{}.dat'.format(name))
        data = np.fromfile(path, dtype=np.dtype(spec['dtype']))
        rows, cols = spec['shape']
        A = data.reshape(rows, cols)
    return A.astype(np.float64) if A.dtype != np.float64 else A


def compute_cur_error(A, U, s, Vt, rank):
    """CUR skeleton approximation error using leverage-score-selected cols/rows."""
    r = min(rank, len(s))
    if r == 0:
        return float(np.linalg.norm(A, 'fro'))

    # Column leverage scores from right singular vectors
    V_r = Vt[:r, :].T  # (n, r)
    col_lev = np.sum(V_r ** 2, axis=1)

    # Row leverage scores from left singular vectors
    U_r = U[:, :r]  # (m, r)
    row_lev = np.sum(U_r ** 2, axis=1)

    # Select top-r indices by leverage score
    J = np.sort(np.argsort(col_lev)[::-1][:r])
    I = np.sort(np.argsort(row_lev)[::-1][:r])

    # CUR = C @ pinv(W) @ R
    C = A[:, J]
    R = A[I, :]
    W = A[np.ix_(I, J)]
    CUR_approx = C @ np.linalg.pinv(W) @ R

    return float(np.linalg.norm(A - CUR_approx, 'fro'))


def main():
    # Load all matrices with corrected specifications
    matrices = {}
    svds = {}
    print("Loading and computing SVDs...")
    for name in sorted(SPECS.keys()):
        spec = SPECS[name]
        A = load_matrix(name, spec)
        matrices[name] = A
        U, s, Vt = np.linalg.svd(A, full_matrices=False)
        svds[name] = (U, s, Vt)
        print("  {}: shape={}, storage_dtype={}, top_sv={:.4f}, norm={:.4f}".format(
            name, A.shape, spec['dtype'], s[0], np.linalg.norm(A, 'fro')))

    # Optimal rank allocation: pool all singular values, sort descending,
    # take top RANK_BUDGET. Minimizes total squared Frobenius error because
    # each selected SV reduces the total squared error by sigma^2.
    print("\nSolving rank allocation (budget={})...".format(RANK_BUDGET))
    pool = []
    for name in sorted(SPECS.keys()):
        _, s, _ = svds[name]
        for j in range(len(s)):
            pool.append((float(s[j]), name))
    pool.sort(key=lambda x: -x[0])

    allocation = {name: 0 for name in SPECS}
    for _, name in pool[:RANK_BUDGET]:
        allocation[name] += 1

    for name in sorted(allocation.keys()):
        print("  {}: allocated_rank={}".format(name, allocation[name]))

    # Compute per-matrix results
    print("\nComputing approximation errors...")
    result_matrices = {}
    total_sq_err = 0.0

    for name in sorted(SPECS.keys()):
        spec = SPECS[name]
        A = matrices[name]
        U, s, Vt = svds[name]

        fnorm = float(np.linalg.norm(A, 'fro'))
        nrank = int(np.sum(s > RELATIVE_TOLERANCE * s[0]))
        arank = allocation[name]

        # SVD approximation error
        if arank >= len(s):
            svd_abs = 0.0
        else:
            svd_abs = float(np.sqrt(np.sum(s[arank:] ** 2)))
        svd_rel = svd_abs / fnorm
        total_sq_err += svd_abs ** 2

        # CUR approximation error
        cur_abs = compute_cur_error(A, U, s, Vt, arank)
        cur_rel = cur_abs / fnorm

        print("  {}: nrank={}, arank={}, svd_err={:.6f}, cur_err={:.6f}".format(
            name, nrank, arank, svd_rel, cur_rel))

        result_matrices[name] = {
            "shape": list(spec['shape']),
            "dtype": spec['dtype'],
            "frobenius_norm": fnorm,
            "numerical_rank": nrank,
            "allocated_rank": arank,
            "svd_relative_error": svd_rel,
            "cur_relative_error": cur_rel,
            "top_5_singular_values": s[:min(5, len(s))].tolist(),
        }

    results = {
        "matrices": result_matrices,
        "rank_allocation": {
            "budget": RANK_BUDGET,
            "total_allocated": sum(allocation.values()),
            "total_squared_svd_error": total_sq_err,
        }
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == '__main__':
    main()
