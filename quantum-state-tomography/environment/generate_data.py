#!/usr/bin/env python3
"""Generate measurement data for quantum state tomography task.
Uses only Python standard library (no numpy).
Deterministic output via random.seed(42).
Writes data to SQLite database, binary calibration files, and YAML manifest.
"""
import random
import math
import os
import sqlite3
import struct

random.seed(42)


def mat_zeros(n, m):
    return [[complex(0)] * m for _ in range(n)]


def mat_eye(n):
    m = mat_zeros(n, n)
    for i in range(n):
        m[i][i] = complex(1)
    return m


def mat_mul(A, B):
    n, p, m_ = len(A), len(B[0]), len(B)
    C = mat_zeros(n, p)
    for i in range(n):
        for j in range(p):
            s = complex(0)
            for k in range(m_):
                s += A[i][k] * B[k][j]
            C[i][j] = s
    return C


def mat_conj_t(A):
    n, m_ = len(A), len(A[0])
    B = mat_zeros(m_, n)
    for i in range(n):
        for j in range(m_):
            B[j][i] = A[i][j].conjugate()
    return B


def kron(A, B):
    na, ma = len(A), len(A[0])
    nb, mb = len(B), len(B[0])
    C = mat_zeros(na * nb, ma * mb)
    for i in range(na):
        for j in range(ma):
            for k in range(nb):
                for l_ in range(mb):
                    C[i * nb + k][j * mb + l_] = A[i][j] * B[k][l_]
    return C


def outer(v):
    n = len(v)
    M = mat_zeros(n, n)
    for i in range(n):
        for j in range(n):
            M[i][j] = v[i] * v[j].conjugate()
    return M


def mat_scale_add(A, a, B, b):
    n, m_ = len(A), len(A[0])
    C = mat_zeros(n, m_)
    for i in range(n):
        for j in range(m_):
            C[i][j] = a * A[i][j] + b * B[i][j]
    return C


def multinomial_sample(n, probs):
    counts = [0] * len(probs)
    cumprobs = []
    s = 0.0
    for p in probs:
        s += p
        cumprobs.append(s)
    if s > 0:
        cumprobs = [c / s for c in cumprobs]
    for _ in range(n):
        r = random.random()
        for i, cp in enumerate(cumprobs):
            if r < cp:
                counts[i] += 1
                break
    return counts


sq2 = math.sqrt(2.0)

U_Z = [[complex(1), complex(0)], [complex(0), complex(1)]]
U_X = [[complex(1.0 / sq2), complex(1.0 / sq2)],
       [complex(1.0 / sq2), complex(-1.0 / sq2)]]
U_Y = [[complex(1.0 / sq2), complex(0, -1.0 / sq2)],
       [complex(1.0 / sq2), complex(0, 1.0 / sq2)]]

basis_map = {'X': U_X, 'Y': U_Y, 'Z': U_Z}


def generate_measurement_data(rho, n_qubits, bases_list, n_shots, readout_errors):
    data = {}
    for bases in bases_list:
        rotations = [basis_map[b] for b in bases]
        U_total = rotations[0]
        for r in rotations[1:]:
            U_total = kron(U_total, r)

        rho_rot = mat_mul(mat_mul(U_total, rho), mat_conj_t(U_total))

        n_outcomes = 2 ** n_qubits
        probs_ideal = [rho_rot[i][i].real for i in range(n_outcomes)]

        probs_noisy = [0.0] * n_outcomes
        for outcome in range(n_outcomes):
            for true_out in range(n_outcomes):
                fp = 1.0
                for q in range(n_qubits):
                    bm = (outcome >> (n_qubits - 1 - q)) & 1
                    bt = (true_out >> (n_qubits - 1 - q)) & 1
                    if bm == bt:
                        fp *= (1 - readout_errors[q])
                    else:
                        fp *= readout_errors[q]
                probs_noisy[outcome] += fp * probs_ideal[true_out]

        s = sum(probs_noisy)
        if s > 0:
            probs_noisy = [p / s for p in probs_noisy]

        counts = multinomial_sample(n_shots, probs_noisy)
        basis_key = ''.join(bases)
        data[basis_key] = {'basis': basis_key, 'counts': counts, 'total_shots': n_shots}

    return data


def generate_calibration(n_qubits, readout_errors, n_cal=50000):
    cal = {}
    for q in range(n_qubits):
        c0 = multinomial_sample(n_cal, [1 - readout_errors[q], readout_errors[q]])
        c1 = multinomial_sample(n_cal, [readout_errors[q], 1 - readout_errors[q]])
        cal[f'qubit_{q}'] = {
            'prepared_0': {'measured_0': c0[0], 'measured_1': c0[1]},
            'prepared_1': {'measured_0': c1[0], 'measured_1': c1[1]}
        }
    return cal


# ---- Define quantum states ----

phi_plus = [complex(1.0 / sq2), complex(0), complex(0), complex(1.0 / sq2)]
rho_A = outer(phi_plus)

I4 = mat_eye(4)
rho_B = mat_scale_add(rho_A, 0.7, I4, 0.3 / 4.0)

ghz = [complex(0)] * 8
ghz[0] = complex(1.0 / sq2)
ghz[7] = complex(1.0 / sq2)
rho_C = outer(ghz)

# ---- Measurement settings ----

bases_2q = [(b1, b2) for b1 in 'XYZ' for b2 in 'XYZ']
bases_3q = [(b1, b2, b3) for b1 in 'XYZ' for b2 in 'XYZ' for b3 in 'XYZ']

re_2q = [0.02, 0.03]
re_3q = [0.02, 0.03, 0.025]
n_shots = 10000

# ---- Generate data (same call order for deterministic reproducibility) ----

print("Generating state A (2-qubit) measurement data...")
data_A = generate_measurement_data(rho_A, 2, bases_2q, n_shots, re_2q)

print("Generating state B (2-qubit) measurement data...")
data_B = generate_measurement_data(rho_B, 2, bases_2q, n_shots, re_2q)

print("Generating state C (3-qubit) measurement data...")
data_C = generate_measurement_data(rho_C, 3, bases_3q, n_shots, re_3q)

print("Generating calibration data...")
cal_2q = generate_calibration(2, re_2q)
cal_3q = generate_calibration(3, re_3q)

# ==== Write SQLite database ====

os.makedirs('/data', exist_ok=True)

conn = sqlite3.connect('/data/tomography.db')
c = conn.cursor()

c.execute('''CREATE TABLE target_systems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    n_qubits INTEGER NOT NULL,
    notes TEXT
)''')

c.execute('''CREATE TABLE acquisition_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id INTEGER NOT NULL,
    pauli_config TEXT NOT NULL,
    n_shots INTEGER NOT NULL,
    FOREIGN KEY (system_id) REFERENCES target_systems(id)
)''')

c.execute('''CREATE TABLE detector_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_id INTEGER NOT NULL,
    bit_pattern INTEGER NOT NULL,
    occurrences INTEGER NOT NULL,
    FOREIGN KEY (setting_id) REFERENCES acquisition_settings(id)
)''')

states_info = [
    ('state_A', 2, 'Unknown 2-qubit pure state'),
    ('state_B', 2, 'Unknown 2-qubit mixed state'),
    ('state_C', 3, 'Unknown 3-qubit state')
]
for name, nq, notes in states_info:
    c.execute('INSERT INTO target_systems (name, n_qubits, notes) VALUES (?, ?, ?)',
              (name, nq, notes))

for state_name, data in [('state_A', data_A), ('state_B', data_B), ('state_C', data_C)]:
    state_id = c.execute('SELECT id FROM target_systems WHERE name=?',
                         (state_name,)).fetchone()[0]
    for basis_key, meas in sorted(data.items()):
        c.execute('''INSERT INTO acquisition_settings
                     (system_id, pauli_config, n_shots) VALUES (?, ?, ?)''',
                  (state_id, basis_key, meas['total_shots']))
        basis_id = c.lastrowid
        for idx, count_val in enumerate(meas['counts']):
            c.execute('''INSERT INTO detector_events
                         (setting_id, bit_pattern, occurrences) VALUES (?, ?, ?)''',
                      (basis_id, idx, count_val))

conn.commit()
conn.close()
print("  SQLite database written to /data/tomography.db")

# ==== Write calibration as binary files ====

for nq_label, cal in [('2qubit', cal_2q), ('3qubit', cal_3q)]:
    n_qubits_cal = len(cal)
    for q in range(n_qubits_cal):
        qcal = cal[f'qubit_{q}']
        dirpath = f'/data/calibration/{nq_label}'
        os.makedirs(dirpath, exist_ok=True)
        filepath = f'{dirpath}/qubit_{q}.bin'
        with open(filepath, 'wb') as f:
            f.write(struct.pack('<4I',
                                qcal['prepared_0']['measured_0'],
                                qcal['prepared_0']['measured_1'],
                                qcal['prepared_1']['measured_0'],
                                qcal['prepared_1']['measured_1']))
print("  Calibration binary files written to /data/calibration/")

# ==== Write YAML manifest ====

yaml_content = """experiment:
  name: quantum_state_tomography
  database: /data/tomography.db

states:
  state_A:
    n_qubits: 2
    calibration_dir: /data/calibration/2qubit
  state_B:
    n_qubits: 2
    calibration_dir: /data/calibration/2qubit
  state_C:
    n_qubits: 3
    calibration_dir: /data/calibration/3qubit

calibration:
  format: binary
  element_type: uint32
  byte_order: little-endian
  layout: |
    Each qubit_N.bin contains 4 unsigned 32-bit integers in little-endian
    byte order. The values represent raw detector counts from single-qubit
    calibration measurements:
      value[0] = count(prepared |0>, measured |0>)
      value[1] = count(prepared |0>, measured |1>)
      value[2] = count(prepared |1>, measured |0>)
      value[3] = count(prepared |1>, measured |1>)
    Total calibration shots per prepared state: 50000.

output:
  results_dir: /app/results
  summary_db: /app/results/summary.db
  summary_schema: |
    CREATE TABLE state_results (
      state_name TEXT PRIMARY KEY,
      n_qubits INTEGER NOT NULL,
      purity REAL NOT NULL,
      is_entangled INTEGER NOT NULL,
      extra_json TEXT NOT NULL
    );
"""

with open('/data/manifest.yaml', 'w') as f:
    f.write(yaml_content)
print("  Manifest written to /data/manifest.yaml")

print("Data generation complete.")
