"""Generate benchmark data: SQLite database (parameters + specs with some transcription errors) and .npy exports (some corrupted)."""
import numpy as np
import sqlite3
import os
import json

D = 10
rng = np.random.default_rng(2026)

os.makedirs('/app/data', exist_ok=True)

# === Generate correct data ===

shifts = rng.uniform(-80, 80, size=(10, D))

rotations = np.zeros((10, D, D))
for i in range(10):
    A = rng.standard_normal((D, D))
    Q, R = np.linalg.qr(A)
    Q = Q @ np.diag(np.sign(np.diag(R)))
    rotations[i] = Q

shuffle_f9 = rng.permutation(D).astype(np.int64)
shuffle_f10 = rng.permutation(D).astype(np.int64)

comp_optima_11 = rng.uniform(-80, 80, size=(3, D))
comp_rotations_11 = np.zeros((3, D, D))
for i in range(3):
    A = rng.standard_normal((D, D))
    Q, R = np.linalg.qr(A)
    Q = Q @ np.diag(np.sign(np.diag(R)))
    comp_rotations_11[i] = Q

comp_optima_12 = rng.uniform(-80, 80, size=(5, D))
comp_rotations_12 = np.zeros((5, D, D))
for i in range(5):
    A = rng.standard_normal((D, D))
    Q, R = np.linalg.qr(A)
    Q = Q @ np.diag(np.sign(np.diag(R)))
    comp_rotations_12[i] = Q

test_points = rng.uniform(-100, 100, size=(5, D))

# === Store data in SQLite database ===

db = sqlite3.connect('/app/benchmark.db')
c = db.cursor()

# --- Parameter tables ---
c.execute('CREATE TABLE shifts (idx INTEGER PRIMARY KEY, data BLOB)')
c.execute('CREATE TABLE rotations (idx INTEGER PRIMARY KEY, data BLOB)')
c.execute('CREATE TABLE shuffles (name TEXT PRIMARY KEY, data BLOB)')
c.execute('CREATE TABLE comp_optima (name TEXT, idx INTEGER, data BLOB, PRIMARY KEY(name, idx))')
c.execute('CREATE TABLE comp_rotations (name TEXT, idx INTEGER, data BLOB, PRIMARY KEY(name, idx))')
c.execute('CREATE TABLE test_points (idx INTEGER PRIMARY KEY, data BLOB)')
c.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)')

# --- Specification tables ---
c.execute('''CREATE TABLE base_function_specs (
    name TEXT PRIMARY KEY,
    formula TEXT,
    notes TEXT
)''')

c.execute('''CREATE TABLE function_specs (
    name TEXT PRIMARY KEY,
    func_type TEXT,
    base_funcs TEXT,
    shift_idx INTEGER,
    rotation_idx INTEGER,
    bias REAL,
    params_json TEXT,
    notes TEXT
)''')

c.execute('''CREATE TABLE construction_formulas (
    func_type TEXT PRIMARY KEY,
    formula TEXT,
    notes TEXT
)''')

c.execute('''CREATE TABLE constraint_specs (
    name TEXT PRIMARY KEY,
    target_func TEXT,
    formula TEXT,
    threshold REAL,
    notes TEXT
)''')

c.execute('''CREATE TABLE reference_values (
    func_name TEXT,
    point_type TEXT,
    expected_value REAL,
    tolerance REAL,
    PRIMARY KEY(func_name, point_type)
)''')

# Insert parameter data (all correct — programmatically generated)
for i in range(10):
    c.execute('INSERT INTO shifts VALUES (?, ?)', (i, shifts[i].tobytes()))
for i in range(10):
    c.execute('INSERT INTO rotations VALUES (?, ?)', (i, rotations[i].tobytes()))
c.execute("INSERT INTO shuffles VALUES ('f9', ?)", (shuffle_f9.tobytes(),))
c.execute("INSERT INTO shuffles VALUES ('f10', ?)", (shuffle_f10.tobytes(),))
for i in range(3):
    c.execute("INSERT INTO comp_optima VALUES ('f11', ?, ?)",
              (i, comp_optima_11[i].tobytes()))
for i in range(5):
    c.execute("INSERT INTO comp_optima VALUES ('f12', ?, ?)",
              (i, comp_optima_12[i].tobytes()))
for i in range(3):
    c.execute("INSERT INTO comp_rotations VALUES ('f11', ?, ?)",
              (i, comp_rotations_11[i].tobytes()))
for i in range(5):
    c.execute("INSERT INTO comp_rotations VALUES ('f12', ?, ?)",
              (i, comp_rotations_12[i].tobytes()))
for i in range(5):
    c.execute("INSERT INTO test_points VALUES (?, ?)", (i, test_points[i].tobytes()))
c.execute("INSERT INTO metadata VALUES ('dimension', ?)", (str(D),))
c.execute("INSERT INTO metadata VALUES ('num_functions', '12')")
c.execute("INSERT INTO metadata VALUES ('search_bounds', '[-100, 100]')")

# Insert base function specifications (transcribed from reference docs)
base_specs = [
    ('sphere',
     'f(z) = sum_{i=0}^{n-1} z_i^2',
     'Minimum at origin, f*=0'),
    ('elliptic',
     'f(z) = sum_{i=0}^{n-1} 10^(6*i/(n-1)) * z_i^2',
     'High-conditioned elliptic. For n=1: f(z)=z_0^2. Condition number 10^6. Note: exponent denominator is (n-1), not n.'),
    ('bent_cigar',
     'f(z) = z_0^2 + 10^6 * sum_{i=1}^{n-1} z_i^2',
     'First component has unit coefficient, rest have 10^6'),
    ('discus',
     'f(z) = 10^6 * z_0^2 + sum_{i=1}^{n-1} z_i^2',
     'First component has 10^6 coefficient, rest have unit'),
    ('rosenbrock',
     'f(z) = sum_{i=0}^{n-2} [100*(z_i^2 - z_{i+1})^2 + (z_i - 1)^2]',
     'Global minimum at z=(1,...,1), f*=0'),
    ('ackley',
     'f(z) = -20*exp(-0.2*sqrt(sum(z_i^2)/n)) - exp(sum(cos(2*pi*z_i))/n) + 20 + e',
     'Minimum at origin, f*=0'),
    ('griewank',
     'f(z) = sum(z_i^2)/4000 - prod_{i=0}^{n-1} cos(z_i/sqrt(i+1)) + 1',
     '0-based indexing: denominators are sqrt(1), sqrt(2), ..., sqrt(n). Note: i+1, not i+2.'),
    ('rastrigin',
     'f(z) = sum_{i=0}^{n-1} [z_i^2 - 10*cos(2*pi*z_i) + 10]',
     'Highly multimodal. Minimum at origin, f*=0'),
]
for name, formula, notes in base_specs:
    c.execute('INSERT INTO base_function_specs VALUES (?, ?, ?)',
              (name, formula, notes))

# Insert construction formulas
constructions = [
    ('shifted_rotated',
     'z = M_{rotation_idx} @ (x - o_{shift_idx}); F(x) = f(z) + bias',
     'Standard shift-and-rotate transformation. Some functions have additional conventions — see function_specs.notes for the specific function.'),
    ('hybrid',
     'z = M_{rotation_idx} @ (x - o_{shift_idx}); z_s = z[shuffle]; partition z_s into consecutive groups of sizes p_1, p_2, ..., p_k; F(x) = sum_{j=1}^{k} f_j(group_j) + bias',
     'Shuffle permutation is applied after shift-rotate. Each group is evaluated independently with its assigned base function. Partition sizes and shuffle name are in params_json.'),
    ('composition',
     'For each component k=0..K-1: d_k^2 = ||x - o_k||^2; w_k = (1/sqrt(d_k^2)) * exp(-d_k^2 / (2*D*sigma_k^2)); if d_k^2 < 1e-30 then w_k = 1e100; W_k = w_k / sum(w_j); z_k = M_k @ (x - o_k); F(x) = sum_k W_k * (lambda_k * f_k(z_k) + c_k) + bias',
     'Distance-weighted combination. When x coincides with component optimum o_k (d^2 < 1e-30), that component dominates via weight 1e100 before normalization. Component optima come from comp_optima table, rotation matrices from comp_rotations table — see params_json for source names. If total weight is zero, use uniform weights 1/K.'),
]
for func_type, formula, notes in constructions:
    c.execute('INSERT INTO construction_formulas VALUES (?, ?, ?)',
              (func_type, formula, notes))

# Insert function specifications
func_specs = [
    ('F1', 'shifted_rotated', 'sphere', 0, 0, 100.0, '{}', ''),
    ('F2', 'shifted_rotated', 'elliptic', 1, 1, 200.0, '{}', ''),
    ('F3', 'shifted_rotated', 'bent_cigar', 2, 2, 300.0, '{}', ''),
    ('F4', 'shifted_rotated', 'discus', 3, 3, 400.0, '{}', ''),
    ('F5', 'shifted_rotated', 'rosenbrock', 4, 4, 500.0, '{}',
     'CEC convention: apply z_hat = z + 1 before evaluating rosenbrock, mapping its natural optimum from (1,...,1) to the origin.'),
    ('F6', 'shifted_rotated', 'ackley', 5, 5, 600.0, '{}', ''),
    ('F7', 'shifted_rotated', 'rastrigin', 6, 6, 700.0, '{}', ''),
    ('F8', 'shifted_rotated', 'griewank', 7, 7, 800.0, '{}', ''),
    ('F9', 'hybrid', 'bent_cigar|ackley|rastrigin', 8, 8, 900.0,
     json.dumps({"partition": [3, 3, 4], "shuffle": "f9"}), ''),
    ('F10', 'hybrid', 'elliptic|sphere|griewank|rastrigin', 9, 9, 1000.0,
     json.dumps({"partition": [3, 3, 2, 2], "shuffle": "f10"}), ''),
    ('F11', 'composition', 'sphere|ackley|rastrigin', -1, -1, 1100.0,
     json.dumps({
         "sigmas": [10.0, 20.0, 30.0],
         "lambdas": [1.0, 10.0, 1.0],
         "component_biases": [0.0, 100.0, 200.0],
         "optima_source": "f11",
         "rotations_source": "f11"
     }),
     'Global optimum at first component optimum (comp_optima f11, idx=0).'),
    ('F12', 'composition', 'elliptic|bent_cigar|discus|sphere|griewank', -1, -1, 1200.0,
     json.dumps({
         "sigmas": [10.0, 20.0, 30.0, 40.0, 50.0],
         "lambdas": [10.0, 1.0, 10.0, 1.0, 1.0],
         "component_biases": [0.0, 100.0, 200.0, 300.0, 400.0],
         "optima_source": "f12",
         "rotations_source": "f12"
     }),
     'Global optimum at first component optimum (comp_optima f12, idx=0).'),
]
for spec in func_specs:
    c.execute('INSERT INTO function_specs VALUES (?, ?, ?, ?, ?, ?, ?, ?)', spec)

# Insert constraint specifications
constraints = [
    ('constraint_F1', 'F1',
     'g(x) = (1/D) * sum((x_i - o_0_i)^2) - 5000; violation = max(0, g)',
     5000.0,
     'Sphere-distance constraint around F1 optimum (shifts idx=0)'),
    ('constraint_F3', 'F3',
     'g(x) = max(|x_i|) - 80; violation = max(0, g)',
     80.0,
     'Box constraint: all coordinates within [-80, 80]'),
    ('constraint_F9', 'F9',
     'g(x) = max(|x_i - o_8_i|) - 50; violation = max(0, g)',
     50.0,
     'L-infinity constraint around F9 optimum (shifts idx=8)'),
]
for name, target, formula, thresh, notes in constraints:
    c.execute('INSERT INTO constraint_specs VALUES (?, ?, ?, ?, ?)',
              (name, target, formula, thresh, notes))

# Insert reference values (expected at optima)
for i in range(12):
    c.execute('INSERT INTO reference_values VALUES (?, ?, ?, ?)',
              (f'F{i+1}', 'optimum', float(100 * (i + 1)), 1e-6))

# === DB Specification Corruptions (transcription errors) ===

# CORRUPTION 3: bent_cigar formula — wrong coefficient (10^4 instead of 10^6)
c.execute("UPDATE base_function_specs SET formula=?, notes=? WHERE name='bent_cigar'",
    ('f(z) = z_0^2 + 10^4 * sum_{i=1}^{n-1} z_i^2',
     'First component has unit coefficient, rest have 10^4'))

# CORRUPTION 4: F8 reference value — wrong expected value (850 instead of 800)
c.execute("UPDATE reference_values SET expected_value=? WHERE func_name='F8'",
    (850.0,))

db.commit()
db.close()

# === Export to .npy files — some with deliberate corruption ===

# Correct exports
np.save('/app/data/shifts.npy', shifts)
np.save('/app/data/shuffle_f9.npy', shuffle_f9)
np.save('/app/data/test_points.npy', test_points)
np.save('/app/data/comp_optima_11.npy', comp_optima_11)
np.save('/app/data/comp_optima_12.npy', comp_optima_12)
np.save('/app/data/comp_rotations_11.npy', comp_rotations_11)
np.save('/app/data/comp_rotations_12.npy', comp_rotations_12)

# CORRUPTION 1: rotation matrix 3 — perturb element to break orthogonality
corrupted_rotations = rotations.copy()
corrupted_rotations[3, 0, 1] += 0.01
np.save('/app/data/rotations.npy', corrupted_rotations)

# CORRUPTION 2: shuffle_f10 — duplicate an entry to break permutation validity
corrupted_shuffle_f10 = shuffle_f10.copy()
corrupted_shuffle_f10[7] = corrupted_shuffle_f10[3]
np.save('/app/data/shuffle_f10.npy', corrupted_shuffle_f10)

print("Data generation complete.")
