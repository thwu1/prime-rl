#!/usr/bin/env python3
"""Generate the pipeline environment with multi-format data storage.

Creates:
- pipeline.db: SQLite database with matrix registry, config, and execution logs
- data/mat_alpha.h5, data/mat_beta.h5: HDF5 matrix files
- data/mat_gamma.dat, data/mat_delta.dat, data/mat_epsilon.dat: raw binary files
- pipeline.py: broken/incomplete pipeline script
- NOTES.txt: development notes with clues
"""
import numpy as np
import h5py
import sqlite3
import json
import os


def main():
    rng = np.random.RandomState(98765)

    base_dir = '/app/pipeline'
    data_dir = os.path.join(base_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    # === mat_alpha: 500x200, float64, exponential SV decay — HDF5 ===
    U_a, _ = np.linalg.qr(rng.randn(500, 200))
    V_a, _ = np.linalg.qr(rng.randn(200, 200))
    s_a = 95.0 * np.exp(-np.arange(200) * 0.1)
    mat_alpha = U_a @ np.diag(s_a) @ V_a.T
    with h5py.File(os.path.join(data_dir, 'mat_alpha.h5'), 'w') as f:
        ds = f.create_dataset('matrix', data=mat_alpha.astype(np.float64))
        ds.attrs['source'] = 'kernel_evaluation'
        ds.attrs['created'] = '2026-01-10'

    # === mat_beta: 300x300, float64, symmetric, polynomial SV decay — HDF5 ===
    Q_b, _ = np.linalg.qr(rng.randn(300, 300))
    s_b = np.array([80.0 / (i + 1.0) ** 1.5 for i in range(300)])
    mat_beta = Q_b @ np.diag(s_b) @ Q_b.T
    mat_beta = 0.5 * (mat_beta + mat_beta.T)
    with h5py.File(os.path.join(data_dir, 'mat_beta.h5'), 'w') as f:
        ds = f.create_dataset('matrix', data=mat_beta.astype(np.float64))
        ds.attrs['source'] = 'covariance'
        ds.attrs['symmetric'] = True
        ds.attrs['created'] = '2026-01-10'

    # === mat_gamma: 400x150, float32 (stored as single precision!) — raw binary ===
    U_g, _ = np.linalg.qr(rng.randn(400, 150))
    V_g, _ = np.linalg.qr(rng.randn(150, 150))
    s_g = np.zeros(150)
    s_g[:20] = np.linspace(55.0, 15.0, 20)
    s_g[20:] = 0.05 * np.exp(-np.arange(130) * 0.05)
    mat_gamma_f64 = U_g @ np.diag(s_g) @ V_g.T
    mat_gamma = mat_gamma_f64.astype(np.float32)
    mat_gamma.tofile(os.path.join(data_dir, 'mat_gamma.dat'))

    # === mat_delta: 250x250, float64, clustered SVs — raw binary ===
    U_d, _ = np.linalg.qr(rng.randn(250, 250))
    V_d, _ = np.linalg.qr(rng.randn(250, 250))
    s_d = np.concatenate([
        np.linspace(100.0, 90.0, 10),
        np.linspace(45.0, 40.0, 10),
        np.linspace(8.0, 5.0, 30),
        np.linspace(1.0, 0.1, 100),
        np.linspace(0.01, 0.001, 100),
    ])
    mat_delta = U_d @ np.diag(s_d) @ V_d.T
    mat_delta.astype(np.float64).tofile(os.path.join(data_dir, 'mat_delta.dat'))

    # === mat_epsilon: 200x400, float64, exponential SV decay — raw binary ===
    U_e, _ = np.linalg.qr(rng.randn(200, 200))
    V_e, _ = np.linalg.qr(rng.randn(400, 200))
    s_e = 40.0 * np.exp(-np.arange(200) * 0.12)
    mat_epsilon = U_e @ np.diag(s_e) @ V_e.T
    mat_epsilon.astype(np.float64).tofile(os.path.join(data_dir, 'mat_epsilon.dat'))

    # === Compute norms for logs ===
    norm_alpha = float(np.linalg.norm(mat_alpha, 'fro'))
    norm_beta = float(np.linalg.norm(mat_beta, 'fro'))

    # === Create SQLite pipeline database ===
    db_path = os.path.join(base_dir, 'pipeline.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Pipeline configuration table
    c.execute('''CREATE TABLE pipeline_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        description TEXT
    )''')
    config_entries = [
        ('relative_tolerance', '0.01',
         'Threshold for numerical rank: sigma > tol * sigma_max'),
        ('rank_budget', '60',
         'Total rank budget distributed across all matrices'),
        ('error_metric', 'frobenius',
         'Norm used for approximation error measurement'),
        ('compute_cur', 'true',
         'Whether to compute CUR skeleton approximation'),
        ('leverage_score_method', 'exact',
         'Method for leverage score computation (exact or approximate)'),
    ]
    c.executemany('INSERT INTO pipeline_config VALUES (?, ?, ?)', config_entries)

    # Matrix registry table (with deliberate errors)
    c.execute('''CREATE TABLE matrix_registry (
        name TEXT PRIMARY KEY,
        rows INTEGER NOT NULL,
        cols INTEGER NOT NULL,
        dtype TEXT NOT NULL DEFAULT 'float64',
        format TEXT NOT NULL,
        filepath TEXT NOT NULL,
        source TEXT,
        notes TEXT
    )''')
    registry_entries = [
        ('mat_alpha', 500, 200, 'float64', 'hdf5', 'data/mat_alpha.h5',
         'kernel_evaluation', 'Kernel matrix from BEM discretization'),
        ('mat_beta', 300, 300, 'float64', 'hdf5', 'data/mat_beta.h5',
         'covariance', 'Symmetric covariance matrix'),
        ('mat_gamma', 400, 150, 'float64', 'raw_binary', 'data/mat_gamma.dat',
         'snapshot_matrix', 'POD snapshot matrix from CFD'),
        ('mat_delta', 250, 200, 'float64', 'raw_binary', 'data/mat_delta.dat',
         'transfer_operator', 'Transfer operator discretization'),
        ('mat_zeta', 100, 100, 'float64', 'raw_binary', 'data/mat_zeta.dat',
         'boundary_conditions', 'Boundary condition coupling matrix'),
    ]
    c.executemany(
        'INSERT INTO matrix_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        registry_entries
    )

    # Execution log table with JSON details blobs
    c.execute('''CREATE TABLE run_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        level TEXT NOT NULL,
        component TEXT NOT NULL,
        message TEXT NOT NULL,
        details TEXT
    )''')
    log_entries = [
        ('2026-01-15 14:32:01', 'INFO', 'pipeline',
         'Pipeline v2.3.1 starting',
         json.dumps({"version": "2.3.1", "python": "3.12.3", "numpy": "2.1.3"})),
        ('2026-01-15 14:32:01', 'INFO', 'registry',
         'Loading matrix registry from pipeline.db',
         json.dumps({"table": "matrix_registry", "entry_count": 5,
                     "formats": {"hdf5": 2, "raw_binary": 3}})),
        ('2026-01-15 14:32:02', 'INFO', 'loader',
         'Loaded mat_alpha from HDF5',
         json.dumps({"format": "hdf5", "filepath": "data/mat_alpha.h5",
                     "h5_dataset": "matrix", "h5_shape": [500, 200],
                     "h5_dtype": "float64", "frobenius_norm": norm_alpha})),
        ('2026-01-15 14:32:03', 'INFO', 'loader',
         'Loaded mat_beta from HDF5',
         json.dumps({"format": "hdf5", "filepath": "data/mat_beta.h5",
                     "h5_dataset": "matrix", "h5_shape": [300, 300],
                     "h5_dtype": "float64", "frobenius_norm": norm_beta,
                     "symmetric": True})),
        ('2026-01-15 14:32:04', 'INFO', 'loader',
         'Attempting to load mat_gamma from raw binary',
         json.dumps({"format": "raw_binary", "filepath": "data/mat_gamma.dat",
                     "registry_dtype": "float64", "registry_shape": [400, 150],
                     "expected_bytes": 400 * 150 * 8,
                     "actual_file_bytes": 400 * 150 * 4})),
        ('2026-01-15 14:32:04', 'ERROR', 'loader',
         'File size mismatch for mat_gamma',
         json.dumps({"expected_bytes": 400 * 150 * 8,
                     "actual_bytes": 400 * 150 * 4,
                     "byte_ratio": 0.5,
                     "diagnostic": "actual element size is 4 bytes, not 8"})),
        ('2026-01-15 14:32:04', 'FATAL', 'pipeline',
         'Pipeline aborted due to data integrity error',
         json.dumps({"failed_at": "mat_gamma",
                     "matrices_loaded": ["mat_alpha", "mat_beta"],
                     "matrices_remaining": ["mat_delta", "mat_zeta"]})),
    ]
    c.executemany(
        'INSERT INTO run_log (timestamp, level, component, message, details) '
        'VALUES (?, ?, ?, ?, ?)',
        log_entries
    )

    conn.commit()
    conn.close()

    # === pipeline.py (broken/incomplete script) ===
    pipeline_code = '''#!/usr/bin/env python3
"""Model reduction pipeline - computes low-rank approximations under rank budget.

Reads matrix registry and configuration from pipeline.db (SQLite).
Supports HDF5 and raw binary matrix formats.
"""
import numpy as np
import sqlite3
import json
import sys
import os


def load_hdf5_matrix(path, rows, cols, dtype="float64"):
    """Load matrix from HDF5 file."""
    import h5py
    with h5py.File(path, 'r') as f:
        data = f['matrix'][:]
    if data.shape != (rows, cols):
        raise ValueError(
            "Shape mismatch for {}: expected ({},{}), got {}".format(
                path, rows, cols, data.shape))
    return data.astype(np.dtype(dtype))


def load_raw_matrix(path, rows, cols, dtype="float64"):
    """Load matrix from raw binary file."""
    data = np.fromfile(path, dtype=np.dtype(dtype))
    expected = rows * cols
    if data.size != expected:
        raise ValueError(
            "Size mismatch for {}: expected {} elements ({}x{} {}), "
            "got {} elements ({} bytes)".format(
                path, expected, rows, cols, dtype, data.size,
                os.path.getsize(path)
            )
        )
    return data.reshape(rows, cols)


def compute_numerical_rank(singular_values, tol):
    """Count singular values above tol * sigma_max."""
    threshold = tol * singular_values[0]
    return int(np.sum(singular_values > threshold))


def main():
    db_path = "/app/pipeline/pipeline.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Read configuration
    config = {}
    for row in conn.execute("SELECT key, value FROM pipeline_config"):
        config[row['key']] = row['value']
    tol = float(config['relative_tolerance'])
    budget = int(config['rank_budget'])

    # Read matrix registry
    matrices = {}
    for row in conn.execute("SELECT * FROM matrix_registry"):
        name = row['name']
        filepath = os.path.join("/app/pipeline", row['filepath'])
        if not os.path.exists(filepath):
            print("WARNING: {} not found, skipping {}".format(filepath, name))
            continue

        fmt = row['format']
        dtype = row['dtype']
        rows, cols = row['rows'], row['cols']
        print("Loading {} from {} (format={})...".format(name, filepath, fmt))

        try:
            if fmt == 'hdf5':
                A = load_hdf5_matrix(filepath, rows, cols, dtype)
            elif fmt == 'raw_binary':
                A = load_raw_matrix(filepath, rows, cols, dtype)
            else:
                print("ERROR: Unknown format '{}' for {}".format(fmt, name))
                sys.exit(1)
            matrices[name] = A
            print("  shape={}, frobenius_norm={:.6f}".format(
                A.shape, np.linalg.norm(A)))
        except ValueError as e:
            print("ERROR: {}".format(e))
            sys.exit(1)

    conn.close()

    # Compute SVD for each loaded matrix
    svd_data = {}
    for name, A in matrices.items():
        print("Computing SVD of {}...".format(name))
        U, s, Vt = np.linalg.svd(A, full_matrices=False)
        svd_data[name] = (U, s, Vt)
        nr = int(np.sum(s > tol * s[0]))
        print("  numerical rank (tol={}): {}".format(tol, nr))

    # TODO: rank allocation across matrices to minimize total approximation error
    # Need to distribute 'budget' ranks optimally

    # TODO: compute SVD and CUR approximation errors at allocated ranks

    # TODO: write results to /app/results.json

    print("Pipeline incomplete - rank allocation and error computation "
          "not implemented.")
    sys.exit(1)


if __name__ == "__main__":
    main()
'''
    with open(os.path.join(base_dir, 'pipeline.py'), 'w') as f:
        f.write(pipeline_code)

    # === NOTES.txt ===
    notes = """Pipeline Development Notes
==========================
2026-01-10: Initial setup. Matrices mat_alpha, mat_beta stored as HDF5 in data/.
            Matrices mat_gamma, mat_delta stored as raw binary in data/.
            All metadata goes in pipeline.db -> matrix_registry table.
            Processing config in pipeline.db -> pipeline_config table.
            Run logs in pipeline.db -> run_log table (details column is JSON).

2026-01-13: Generated mat_epsilon (200 x 400, float64, raw binary) from the
            boundary layer simulation. Saved to data/mat_epsilon.dat.
            TODO: add entry to matrix_registry in pipeline.db.

2026-01-14: Noticed mat_gamma was re-exported from the snapshot tool in single
            precision (float32). Need to update dtype in the registry.

2026-01-15: Pipeline crashed on mat_gamma load. Check run_log table in
            pipeline.db for error details. The details column has byte counts
            that reveal the dtype issue. Use json_extract() in sqlite3 or
            pipe through jq to read the structured error info.
"""
    with open(os.path.join(base_dir, 'NOTES.txt'), 'w') as f:
        f.write(notes)

    print("Pipeline environment generated successfully.")


if __name__ == '__main__':
    main()
