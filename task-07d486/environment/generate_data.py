
"""Generate binary data files, SQLite reference database, and log files for the Ewald task."""
import numpy as np
import random
import sqlite3
import os

# ============================================================
# 1. Generate NaCl crystal configuration
# ============================================================
N_cells = 4
d = 1.0
L = N_cells * d

positions = []
charges = []
for ix in range(N_cells):
    for iy in range(N_cells):
        for iz in range(N_cells):
            x = ix * d
            y = iy * d
            z = iz * d
            q = 1.0 if (ix + iy + iz) % 2 == 0 else -1.0
            positions.append([x, y, z])
            charges.append(q)

positions = np.array(positions)
charges = np.array(charges)
n_particles = len(charges)

os.makedirs('/app/data', exist_ok=True)
np.savez('/app/data/nacl_crystal.npz',
         positions=positions, charges=charges,
         box_length=np.array(L), d=np.array(d),
         n_particles=np.array(n_particles))

# ============================================================
# 2. Generate perturbed crystal configuration
# ============================================================
random.seed(42)
sigma = 0.05

perturbed_positions = []
for pos in positions:
    px = (pos[0] + random.gauss(0, sigma)) % L
    py = (pos[1] + random.gauss(0, sigma)) % L
    pz = (pos[2] + random.gauss(0, sigma)) % L
    perturbed_positions.append([px, py, pz])

perturbed_positions = np.array(perturbed_positions)
np.savez('/app/data/perturbed_crystal.npz',
         positions=perturbed_positions, charges=charges,
         box_length=np.array(L), d=np.array(d),
         n_particles=np.array(n_particles))

# ============================================================
# 3. Create parameters file
# ============================================================
with open('/app/data/params.ini', 'w') as f:
    f.write("[ewald]\n")
    f.write("alpha = 1.25\n")
    f.write("k_max = 7\n")

# ============================================================
# 4. Create SQLite reference database
# ============================================================
db_path = '/app/data/reference.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute('''CREATE TABLE reference_values (
    name TEXT PRIMARY KEY,
    value REAL,
    tolerance REAL,
    unit TEXT,
    description TEXT
)''')

c.execute("INSERT INTO reference_values VALUES (?, ?, ?, ?, ?)",
          ('nacl_madelung', 1.7475645946, 0.001, 'dimensionless',
           'Known NaCl Madelung constant for rock-salt structure'))
c.execute("INSERT INTO reference_values VALUES (?, ?, ?, ?, ?)",
          ('crystal_max_force_threshold', 0.005, None, 'force_units',
           'Maximum acceptable force magnitude on perfect crystal ions'))

c.execute('''CREATE TABLE output_schema (
    field_name TEXT PRIMARY KEY,
    field_type TEXT,
    description TEXT
)''')

schema_entries = [
    ('nacl_madelung', 'float',
     'Madelung constant extracted via M = -2 * E_total * d / N'),
    ('nacl_max_force', 'float',
     'Maximum force magnitude on any ion in the perfect crystal'),
    ('perturbed_energy', 'float',
     'Total electrostatic energy of the perturbed configuration'),
    ('perturbed_energy_components', 'dict',
     'Energy decomposition: {"real": float, "recip": float, "self": float}'),
    ('perturbed_forces', 'list',
     'N x 3 array of force vectors [fx, fy, fz] for each particle'),
    ('perturbed_force_sum', 'list',
     'Total force vector [fx_total, fy_total, fz_total]'),
    ('fd_check', 'dict',
     'Finite-difference check on particle 0 along x-axis: '
     '{"dx": 1e-5, "energy_plus": float, "energy_minus": float, '
     '"numerical_force_x": -(E_plus - E_minus) / (2*dx)}')
]
for entry in schema_entries:
    c.execute("INSERT INTO output_schema VALUES (?, ?, ?)", entry)

c.execute('''CREATE TABLE system_info (
    key TEXT PRIMARY KEY,
    value TEXT
)''')
system_entries = [
    ('crystal_file', 'nacl_crystal.npz'),
    ('perturbed_file', 'perturbed_crystal.npz'),
    ('nearest_neighbor_distance', '1.0'),
    ('n_particles', '64'),
    ('box_length', '4.0')
]
for entry in system_entries:
    c.execute("INSERT INTO system_info VALUES (?, ?)", entry)

conn.commit()
conn.close()

# ============================================================
# 5. Create log files from previous (failed) validation runs
# ============================================================
os.makedirs('/app/logs', exist_ok=True)

log1 = """\
=== Ewald Pipeline Validation Run ===
Date: 2024-03-15T14:22:07
Config: nacl_crystal.npz
Parameters: alpha=1.25, k_max=7

[COMPUTE] Real-space energy:     -42.8173
[COMPUTE] Reciprocal energy:       3.4126
[COMPUTE] Self-energy:           -14.0901
[COMPUTE] Total energy:          -53.4948
[COMPUTE] Madelung constant:      -1.6717
[COMPUTE] Max crystal force:        0.2847

[VALIDATE] FAILED
  Madelung: -1.6717 (expected: 1.7476 +/- 0.001)
  Max force: 0.2847 (expected: < 0.005)
"""

log2 = """\
=== Ewald Pipeline Validation Run ===
Date: 2024-04-02T09:15:33
Config: nacl_crystal.npz
Parameters: alpha=1.50, k_max=5

[COMPUTE] Real-space energy:     -38.5641
[COMPUTE] Reciprocal energy:       4.8922
[COMPUTE] Self-energy:           -20.2535
[COMPUTE] Total energy:          -53.9254
[COMPUTE] Madelung constant:      -1.6852
[COMPUTE] Max crystal force:        0.1893

[VALIDATE] FAILED
  Madelung: -1.6852 (expected: 1.7476 +/- 0.001)
  Max force: 0.1893 (expected: < 0.005)
"""

with open('/app/logs/run_20240315.log', 'w') as f:
    f.write(log1)
with open('/app/logs/run_20240402.log', 'w') as f:
    f.write(log2)

print(f"Generated {n_particles} particles in box L={L}")
print(f"Data files written to /app/data/")
print(f"Reference database: /app/data/reference.db")
print(f"Log files written to /app/logs/")
