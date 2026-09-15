"""Generate task environment: HDF5 particle data, YAML config, SQLite profiles."""

import numpy as np
import h5py
import yaml
import sqlite3
import os
import sys

np.random.seed(42)

# ── Particle generation ─────────────────────────────────────────────
Lx, Ly, Lz = 100.0, 50.0, 200.0
N = 50000

n1 = int(0.3 * N)
n2 = int(0.25 * N)
n3 = int(0.2 * N)
n4 = N - n1 - n2 - n3

particles = np.zeros((N, 3))

idx = 0
# Cluster 1: lower-left region
particles[idx:idx+n1, 0] = np.random.normal(25, 8, n1)
particles[idx:idx+n1, 1] = np.random.normal(12.5, 4, n1)
particles[idx:idx+n1, 2] = np.random.normal(50, 16, n1)
idx += n1

# Cluster 2: upper-right region
particles[idx:idx+n2, 0] = np.random.normal(75, 6, n2)
particles[idx:idx+n2, 1] = np.random.normal(37.5, 3, n2)
particles[idx:idx+n2, 2] = np.random.normal(150, 12, n2)
idx += n2

# Cluster 3: centre
particles[idx:idx+n3, 0] = np.random.normal(50, 10, n3)
particles[idx:idx+n3, 1] = np.random.normal(25, 5, n3)
particles[idx:idx+n3, 2] = np.random.normal(100, 20, n3)
idx += n3

# Uniform background
particles[idx:idx+n4, 0] = np.random.uniform(0, Lx, n4)
particles[idx:idx+n4, 1] = np.random.uniform(0, Ly, n4)
particles[idx:idx+n4, 2] = np.random.uniform(0, Lz, n4)

# Wrap into periodic box
particles[:, 0] = particles[:, 0] % Lx
particles[:, 1] = particles[:, 1] % Ly
particles[:, 2] = particles[:, 2] % Lz

# Velocities and types (not relevant to decomposition, but realistic)
velocities = np.random.normal(0, 1.0, (N, 3))
atom_types = np.random.choice(
    [0, 1, 2], size=N, p=[0.6, 0.3, 0.1]).astype(np.int32)

# ── Save HDF5 ───────────────────────────────────────────────────────
os.makedirs('/app/data', exist_ok=True)
with h5py.File('/app/data/particles.h5', 'w') as f:
    f.create_dataset('positions', data=particles)
    f.create_dataset('velocities', data=velocities)
    f.create_dataset('atom_types', data=atom_types)
    meta = f.create_group('metadata')
    meta.create_dataset('box_dimensions', data=np.array([Lx, Ly, Lz]))
    meta.create_dataset('n_particles', data=N)
    meta.create_dataset('timestep', data=0.001)

# ── Save YAML config ────────────────────────────────────────────────
config = {
    'simulation': {
        'name': 'cluster_md_benchmark',
        'domain': {
            'extents': [Lx, Ly, Lz],
            'periodicity': [True, True, True],
        },
        'interactions': {
            'type': 'lennard-jones',
            'cutoff': 5.0,
            'skin_distance': 1.0,
        },
        'timestep_fs': 1.0,
        'ensemble': 'NVE',
    },
    'scaling_study': {
        'target_counts': [24, 48, 96],
    },
    'platform': {
        'architecture': 'x86_64',
        'network': {
            'topology': 'fat-tree',
            'msg_startup_latency_sec': 1e-5,
            'per_datum_transfer_cost_sec': 1e-9,
        },
        'compute': {
            'per_particle_flop_cost_sec': 1e-7,
        },
        'memory': {
            'per_node_gb': 128,
            'cache_line_bytes': 64,
        },
    },
}

with open('/app/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False)

# ── Generate benchmark profiles (SQLite) ─────────────────────────────
sys.path.insert(0, '/app')
from sim.perf_model import evaluate_grid
from sim.decompose import assign_particles
from sim.comm import compute_face_halos, aggregate_comm_costs

cutoff = 5.0
alpha = 1e-5
beta = 1e-9
t_compute = 1e-7

# Suboptimal grids chosen for profiling
profile_grids = {
    24: [(1, 4, 6), (4, 1, 6), (2, 2, 6)],
    48: [(2, 4, 6), (4, 2, 6), (1, 4, 12)],
    96: [(2, 4, 12), (4, 4, 6), (8, 2, 6)],
}

os.makedirs('/app/profiles', exist_ok=True)
db_path = '/app/profiles/benchmarks.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute('''CREATE TABLE configurations (
    config_id INTEGER PRIMARY KEY AUTOINCREMENT,
    processor_count INTEGER NOT NULL,
    grid_x INTEGER NOT NULL,
    grid_y INTEGER NOT NULL,
    grid_z INTEGER NOT NULL,
    run_date TEXT NOT NULL,
    notes TEXT
)''')

c.execute('''CREATE TABLE rank_metrics (
    config_id INTEGER NOT NULL,
    rank INTEGER NOT NULL,
    particle_count INTEGER NOT NULL,
    halo_particles_received INTEGER NOT NULL,
    computation_time_sec REAL NOT NULL,
    communication_time_sec REAL NOT NULL,
    FOREIGN KEY (config_id) REFERENCES configurations(config_id)
)''')

c.execute('''CREATE TABLE run_summary (
    config_id INTEGER PRIMARY KEY,
    t_total_sec REAL NOT NULL,
    t_computation_sec REAL NOT NULL,
    t_communication_sec REAL NOT NULL,
    load_imbalance_ratio REAL NOT NULL,
    total_halo_volume INTEGER NOT NULL,
    max_particles_per_rank INTEGER NOT NULL,
    FOREIGN KEY (config_id) REFERENCES configurations(config_id)
)''')

box = [Lx, Ly, Lz]
config_id = 0
for P, grids in profile_grids.items():
    for grid in grids:
        config_id += 1
        result = evaluate_grid(particles, grid, box, cutoff,
                               alpha, beta, t_compute)

        c.execute(
            'INSERT INTO configurations '
            '(config_id, processor_count, grid_x, grid_y, grid_z, run_date, notes) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (config_id, P, grid[0], grid[1], grid[2],
             '2024-11-15', f'benchmark run for P={P}'))

        c.execute(
            'INSERT INTO run_summary '
            '(config_id, t_total_sec, t_computation_sec, t_communication_sec, '
            ' load_imbalance_ratio, total_halo_volume, max_particles_per_rank) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (config_id, result['T_total'], result['T_comp'], result['T_comm'],
             result['load_imbalance'], result['comm_volume'],
             result['max_particles_per_rank']))

        # Per-rank breakdown
        px, py, pz = grid
        n_ranks = px * py * pz
        ix, iy, iz, dx, dy, dz = assign_particles(particles, grid, box)
        rank_id = ix * (py * pz) + iy * pz + iz
        rank_counts = np.bincount(rank_id, minlength=n_ranks)

        face_sends, _, _ = compute_face_halos(
            particles, grid, box, cutoff,
            (ix, iy, iz), (dx, dy, dz))
        halo_totals, comm_times = aggregate_comm_costs(
            face_sends, grid, n_ranks, alpha, beta)

        for r in range(n_ranks):
            c.execute(
                'INSERT INTO rank_metrics '
                '(config_id, rank, particle_count, halo_particles_received, '
                ' computation_time_sec, communication_time_sec) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (config_id, r, int(rank_counts[r]), int(halo_totals[r]),
                 float(rank_counts[r]) * t_compute, float(comm_times[r])))

conn.commit()
conn.close()

print(f"Generated {N} particles -> /app/data/particles.h5")
print(f"Config -> /app/config.yaml")
print(f"Profiles ({config_id} runs) -> {db_path}")
