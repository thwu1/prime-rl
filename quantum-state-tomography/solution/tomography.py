#!/usr/bin/env python3
"""Quantum state tomography: reconstruction with readout error mitigation.

Reads measurement data from SQLite database and calibration from binary files,
reconstructs density matrices, and outputs results in multiple formats.
"""

import numpy as np
import json
import os
import sqlite3
import struct
import yaml
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


# ---- Data loading ----

def load_manifest():
    with open('/data/manifest.yaml') as f:
        return yaml.safe_load(f)


def load_measurements_from_db(db_path, state_name):
    """Query SQLite database for measurement data using multi-table JOINs."""
    conn = sqlite3.connect(db_path)

    row = conn.execute(
        'SELECT id, n_qubits FROM target_systems WHERE name = ?',
        (state_name,)
    ).fetchone()
    state_id, n_qubits = row

    rows = conn.execute('''
        SELECT a.pauli_config, d.bit_pattern, d.occurrences, a.n_shots
        FROM acquisition_settings a
        JOIN detector_events d ON d.setting_id = a.id
        WHERE a.system_id = ?
        ORDER BY a.pauli_config, d.bit_pattern
    ''', (state_id,)).fetchall()
    conn.close()

    data = {}
    for pauli_config, bit_pattern, occurrences, n_shots_val in rows:
        if pauli_config not in data:
            data[pauli_config] = {
                'basis': pauli_config,
                'counts': [],
                'total_shots': n_shots_val
            }
        data[pauli_config]['counts'].append((bit_pattern, occurrences))

    for basis_key in data:
        sorted_counts = sorted(data[basis_key]['counts'], key=lambda x: x[0])
        data[basis_key]['counts'] = [c for _, c in sorted_counts]

    return data, n_qubits


def load_calibration_binary(cal_dir, n_qubits):
    """Load per-qubit calibration from binary files and build assignment matrix."""
    single_qubit_matrices = []
    for q in range(n_qubits):
        filepath = os.path.join(cal_dir, f'qubit_{q}.bin')
        with open(filepath, 'rb') as f:
            raw = struct.unpack('<4I', f.read(16))
        prep0_meas0, prep0_meas1, prep1_meas0, prep1_meas1 = raw
        total_0 = prep0_meas0 + prep0_meas1
        total_1 = prep1_meas0 + prep1_meas1
        # Column-stochastic assignment matrix: M[measured][prepared]
        M_q = np.array([
            [prep0_meas0 / total_0, prep1_meas0 / total_1],
            [prep0_meas1 / total_0, prep1_meas1 / total_1]
        ])
        single_qubit_matrices.append(M_q)

    M = single_qubit_matrices[0]
    for i in range(1, n_qubits):
        M = np.kron(M, single_qubit_matrices[i])
    return M


# ---- Pauli basis eigenstates ----

PLUS = np.array([1, 1], dtype=complex) / np.sqrt(2)
MINUS = np.array([1, -1], dtype=complex) / np.sqrt(2)
PLUS_I = np.array([1, 1j], dtype=complex) / np.sqrt(2)
MINUS_I = np.array([1, -1j], dtype=complex) / np.sqrt(2)
ZERO = np.array([1, 0], dtype=complex)
ONE = np.array([0, 1], dtype=complex)

BASIS_STATES = {
    'X': [PLUS, MINUS],
    'Y': [PLUS_I, MINUS_I],
    'Z': [ZERO, ONE]
}


# ---- Readout error mitigation ----

def mitigate_readout_errors(counts, M):
    """Invert assignment matrix to correct measured probabilities."""
    probs = np.array(counts, dtype=float) / sum(counts)
    M_inv = np.linalg.inv(M)
    probs_corrected = M_inv @ probs
    probs_corrected = np.maximum(probs_corrected, 0)
    total = probs_corrected.sum()
    if total > 0:
        probs_corrected /= total
    return probs_corrected


# ---- Measurement projectors ----

def get_projectors(bases_str, n_qubits):
    """Compute measurement projectors for a given Pauli basis setting."""
    projectors = []
    n_outcomes = 2 ** n_qubits
    for outcome in range(n_outcomes):
        proj = np.array([[1.0 + 0j]])
        for q in range(n_qubits):
            bit = (outcome >> (n_qubits - 1 - q)) & 1
            state = BASIS_STATES[bases_str[q]][bit]
            proj = np.kron(proj, np.outer(state, state.conj()))
        projectors.append(proj)
    return projectors


# ---- Maximum Likelihood Estimation ----

def mle_tomography(measurement_data, M, n_qubits, max_iter=5000, tol=1e-10):
    """Iterative MLE reconstruction of a physical density matrix."""
    d = 2 ** n_qubits

    all_projectors = []
    all_frequencies = []
    total_counts = 0

    for basis_key, meas in measurement_data.items():
        counts = meas['counts']
        corrected_probs = mitigate_readout_errors(counts, M)
        projectors = get_projectors(basis_key, n_qubits)

        n_basis_shots = sum(counts)
        for proj, freq in zip(projectors, corrected_probs):
            all_projectors.append(proj)
            all_frequencies.append(freq * n_basis_shots)
        total_counts += n_basis_shots

    all_frequencies = [f / total_counts for f in all_frequencies]

    rho = np.eye(d, dtype=complex) / d

    for iteration in range(max_iter):
        R = np.zeros((d, d), dtype=complex)
        for proj, freq in zip(all_projectors, all_frequencies):
            if freq > 1e-15:
                p = np.real(np.trace(proj @ rho))
                p = max(p, 1e-15)
                R += (freq / p) * proj

        rho_new = R @ rho @ R
        rho_new = (rho_new + rho_new.conj().T) / 2
        tr = np.real(np.trace(rho_new))
        if tr > 1e-15:
            rho_new /= tr

        diff = np.linalg.norm(rho_new - rho, 'fro')
        rho = rho_new
        if diff < tol:
            print(f"  MLE converged after {iteration + 1} iterations (diff={diff:.2e})")
            break
    else:
        print(f"  MLE: {max_iter} iterations (final diff={diff:.2e})")

    eigenvalues, eigenvectors = np.linalg.eigh(rho)
    eigenvalues = np.maximum(eigenvalues, 0)
    eigenvalues /= eigenvalues.sum()
    rho = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.conj().T
    rho = (rho + rho.conj().T) / 2

    return rho


# ---- Entanglement measures ----

def compute_purity(rho):
    return float(np.real(np.trace(rho @ rho)))


def compute_concurrence(rho):
    """Wootters concurrence for a 2-qubit density matrix."""
    sigma_y = np.array([[0, -1j], [1j, 0]])
    YY = np.kron(sigma_y, sigma_y)
    rho_tilde = YY @ rho.conj() @ YY
    product = rho @ rho_tilde
    eigenvalues = np.linalg.eigvals(product)
    lambdas = np.sort(np.sqrt(np.maximum(np.real(eigenvalues), 0)))[::-1]
    return float(max(0, lambdas[0] - lambdas[1] - lambdas[2] - lambdas[3]))


def partial_transpose(rho, n_qubits, qubit_idx):
    """Partial transpose of density matrix w.r.t. a single qubit."""
    d = 2 ** n_qubits
    shape = [2] * (2 * n_qubits)
    rho_t = rho.reshape(shape)
    axes = list(range(2 * n_qubits))
    axes[qubit_idx], axes[n_qubits + qubit_idx] = \
        axes[n_qubits + qubit_idx], axes[qubit_idx]
    rho_pt = np.transpose(rho_t, axes).reshape(d, d)
    return rho_pt


def compute_negativity(rho, n_qubits, qubit_idx):
    """Negativity from partial transpose eigenvalues."""
    rho_pt = partial_transpose(rho, n_qubits, qubit_idx)
    eigenvalues = np.real(np.linalg.eigvalsh(rho_pt))
    return float(abs(sum(ev for ev in eigenvalues if ev < -1e-10)))


# ---- State analysis ----

def analyze_2qubit(rho):
    pur = compute_purity(rho)
    conc = compute_concurrence(rho)
    is_entangled = conc > 0.01

    if conc > 0.9:
        ent_type = "maximally_entangled"
    elif conc > 0.01:
        ent_type = "partially_entangled"
    else:
        ent_type = "separable"

    return {
        'purity': round(pur, 6),
        'concurrence': round(conc, 6),
        'is_entangled': bool(is_entangled),
        'entanglement_type': ent_type
    }


def analyze_3qubit(rho):
    pur = compute_purity(rho)

    negativities = []
    for q in range(3):
        neg = compute_negativity(rho, 3, q)
        negativities.append(neg)

    min_neg = min(negativities)
    is_entangled = any(n > 0.01 for n in negativities)
    is_gme = all(n > 0.01 for n in negativities)

    return {
        'purity': round(pur, 6),
        'is_entangled': bool(is_entangled),
        'is_genuine_multipartite_entangled': bool(is_gme),
        'min_bipartite_negativity': round(float(min_neg), 6)
    }


# ---- Visualization ----

def plot_density_matrix(rho, filepath):
    """Generate heatmap visualization of density matrix."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    im1 = axes[0].imshow(rho.real, cmap='RdBu_r', vmin=-0.5, vmax=0.5,
                          interpolation='nearest')
    axes[0].set_title('Real Part')
    plt.colorbar(im1, ax=axes[0], shrink=0.8)

    im2 = axes[1].imshow(rho.imag, cmap='RdBu_r', vmin=-0.5, vmax=0.5,
                          interpolation='nearest')
    axes[1].set_title('Imaginary Part')
    plt.colorbar(im2, ax=axes[1], shrink=0.8)

    plt.suptitle(f'Density Matrix ({rho.shape[0]}x{rho.shape[1]})')
    plt.tight_layout()
    plt.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close()


# ---- Output ----

def save_results(rho, props, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    np.savetxt(os.path.join(output_dir, 'density_matrix_real.csv'),
               rho.real, delimiter=',', fmt='%.10f')
    np.savetxt(os.path.join(output_dir, 'density_matrix_imag.csv'),
               rho.imag, delimiter=',', fmt='%.10f')
    with open(os.path.join(output_dir, 'properties.json'), 'w') as f:
        json.dump(props, f, indent=2)
    plot_density_matrix(rho, os.path.join(output_dir, 'density_matrix.png'))


def write_summary_db(results, db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute('''CREATE TABLE IF NOT EXISTS state_results (
        state_name TEXT PRIMARY KEY,
        n_qubits INTEGER NOT NULL,
        purity REAL NOT NULL,
        is_entangled INTEGER NOT NULL,
        extra_json TEXT NOT NULL
    )''')
    for state_name, n_qubits, props in results:
        purity = props['purity']
        is_entangled = 1 if props.get('is_entangled', False) else 0
        extra = {k: v for k, v in props.items()
                 if k not in ('purity', 'is_entangled')}
        conn.execute(
            'INSERT OR REPLACE INTO state_results VALUES (?, ?, ?, ?, ?)',
            (state_name, n_qubits, purity, is_entangled, json.dumps(extra)))
    conn.commit()
    conn.close()


# ---- Main ----

def main():
    manifest = load_manifest()
    db_path = manifest['experiment']['database']

    all_results = []

    for state_name, state_cfg in manifest['states'].items():
        print(f"\nProcessing {state_name}...")
        n_qubits = state_cfg['n_qubits']
        cal_dir = state_cfg['calibration_dir']

        meas_data, _ = load_measurements_from_db(db_path, state_name)
        M = load_calibration_binary(cal_dir, n_qubits)

        rho = mle_tomography(meas_data, M, n_qubits)

        if n_qubits == 2:
            props = analyze_2qubit(rho)
        elif n_qubits == 3:
            props = analyze_3qubit(rho)
        else:
            props = {'purity': round(compute_purity(rho), 6)}

        print(f"  Properties: {props}")
        save_results(rho, props, f'/app/results/{state_name}')
        all_results.append((state_name, n_qubits, props))

    summary_db = manifest['output']['summary_db']
    write_summary_db(all_results, summary_db)
    print(f"\nSummary database written to {summary_db}")
    print("Tomography complete!")


if __name__ == '__main__':
    main()
