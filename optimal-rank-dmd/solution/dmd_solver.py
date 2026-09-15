#!/usr/bin/env python3
"""

Solution: system identification via spectral decomposition of snapshot
pairs, with noise-adaptive rank selection and dual-format output.
"""
import numpy as np
import h5py
import json
import xml.etree.ElementTree as ET


def parse_output_spec(xml_path):
    """Parse the XML output specification to discover field names,
    format details, and HDF5 group mappings."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    ns = {'o': 'urn:raven:output:1.0'}

    fields = {}
    for rg in root.findall('.//o:ResultGroup', ns):
        group_name = rg.get('name')
        for fld in rg.findall('o:Field', ns):
            fields[fld.get('name')] = {
                'group': group_name,
                'dtype': fld.get('dtype'),
                'format': fld.get('format'),
                'sort_order': fld.get('sort_order'),
            }

    hdf5_groups = {}
    for gm in root.findall('.//o:GroupMapping', ns):
        hdf5_groups[gm.get('result_group')] = gm.get('hdf5_group')

    return fields, hdf5_groups


def determine_rank(singular_values, n_rows, n_cols):
    """Optimal hard threshold for singular value truncation
    (Gavish-Donoho, unknown-noise variant)."""
    beta = min(n_rows, n_cols) / max(n_rows, n_cols)
    omega = 0.56 * beta**3 - 0.95 * beta**2 + 1.82 * beta + 1.43
    threshold = omega * np.median(singular_values)
    rank = int(np.sum(singular_values > threshold))
    return max(rank, 1)


def main():
    # ── Read HDF5 input ─────────────────────────────────────────────────
    with h5py.File('/app/data/system_observations.h5', 'r') as f:
        X_raw = np.array(f['observations/snapshots'])       # (201, n)
        n = int(f['metadata'].attrs['state_dimension'])
        n_pred = int(f['analysis_config'].attrs['prediction_horizon'])

    X = X_raw.T  # (n, num_snapshots)

    # ── Parse XML output specification ──────────────────────────────────
    fields, hdf5_groups = parse_output_spec('/app/config/output_spec.xml')

    # ── Form snapshot-pair matrices ─────────────────────────────────────
    X1 = X[:, :-1]
    X2 = X[:, 1:]
    m = X1.shape[1]

    # ── SVD and rank selection ──────────────────────────────────────────
    U, S, Vt = np.linalg.svd(X1, full_matrices=False)
    r = determine_rank(S, n, m)

    Ur  = U[:, :r]
    Sr  = S[:r]
    Vtr = Vt[:r, :]

    # ── Reduced dynamics ────────────────────────────────────────────────
    A_tilde = Ur.T @ X2 @ Vtr.T @ np.diag(1.0 / Sr)

    eigenvalues, W = np.linalg.eig(A_tilde)

    # ── Exact dynamic modes ─────────────────────────────────────────────
    Phi = X2 @ Vtr.T @ np.diag(1.0 / Sr) @ W

    # ── Initial amplitudes ──────────────────────────────────────────────
    b = np.linalg.lstsq(Phi, X[:, 0], rcond=None)[0]

    # ── Predict future states ───────────────────────────────────────────
    predictions = np.zeros((n, n_pred))
    for j in range(n_pred):
        t = m + 1 + j
        predictions[:, j] = np.real(Phi @ (b * eigenvalues**t))

    # ── Reconstruct training data ───────────────────────────────────────
    num_snapshots = X.shape[1]
    reconstruction = np.zeros((n, num_snapshots), dtype=complex)
    for t in range(num_snapshots):
        reconstruction[:, t] = Phi @ (b * eigenvalues**t)
    reconstruction = np.real(reconstruction)
    recon_rmse = float(np.sqrt(np.mean((reconstruction - X) ** 2)))

    # ── Sort eigenvalues by magnitude (descending, per XML spec) ────────
    sort_idx = np.argsort(-np.abs(eigenvalues))
    eigenvalues_sorted = eigenvalues[sort_idx]
    magnitudes_sorted = np.abs(eigenvalues_sorted)

    # ── Write JSON output ───────────────────────────────────────────────
    results_json = {
        'optimal_rank': r,
        'eigenvalues': [
            [float(e.real), float(e.imag)] for e in eigenvalues_sorted
        ],
        'eigenvalue_magnitudes': [float(m) for m in magnitudes_sorted],
        'predictions': predictions.T.tolist(),
        'reconstruction_rmse': recon_rmse,
    }
    with open('/app/results.json', 'w') as f:
        json.dump(results_json, f, indent=2)

    # ── Write HDF5 output (group hierarchy from XML spec) ───────────────
    with h5py.File('/app/results.h5', 'w') as f:
        # /analysis/rank
        rg = f.create_group(hdf5_groups['rank_analysis'].lstrip('/'))
        rg.create_dataset('optimal_rank', data=r)

        # /analysis/spectral
        sg = f.create_group(hdf5_groups['spectral_analysis'].lstrip('/'))
        eig_data = np.column_stack([eigenvalues_sorted.real,
                                     eigenvalues_sorted.imag])
        sg.create_dataset('eigenvalues', data=eig_data)
        sg.create_dataset('eigenvalue_magnitudes',
                          data=magnitudes_sorted.astype(np.float64))

        # /analysis/forecasting
        fg = f.create_group(hdf5_groups['forecasting'].lstrip('/'))
        fg.create_dataset('predictions', data=predictions.T)

        # /analysis/quality
        qg = f.create_group(hdf5_groups['reconstruction'].lstrip('/'))
        qg.create_dataset('reconstruction_rmse', data=recon_rmse)

    print(f"Optimal rank:        {r}")
    print(f"Eigenvalues:         {eigenvalues_sorted}")
    print(f"Reconstruction RMSE: {recon_rmse:.6f}")
    print("Results written to /app/results.json and /app/results.h5")


if __name__ == '__main__':
    main()
