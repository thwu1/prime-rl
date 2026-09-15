-- SQLite schema for HPC benchmark results database
-- All benchmark results must be stored in these tables.

DROP TABLE IF EXISTS lammps_runs;
DROP TABLE IF EXISTS milc_runs;
DROP TABLE IF EXISTS workflow_runs;
DROP TABLE IF EXISTS milc_scaling;

CREATE TABLE lammps_runs (
    log_file TEXT PRIMARY KEY,
    num_atoms INTEGER NOT NULL,
    num_timesteps INTEGER NOT NULL,
    wall_time_seconds REAL NOT NULL,
    fom REAL NOT NULL,
    pe_per_molecule REAL NOT NULL,
    validation_passed INTEGER NOT NULL CHECK(validation_passed IN (0, 1))
);

CREATE TABLE milc_runs (
    log_file TEXT PRIMARY KEY,
    nodes INTEGER NOT NULL,
    traj2_mean_step_time REAL NOT NULL,
    olcf_fom REAL NOT NULL,
    replicas INTEGER NOT NULL,
    final_fom REAL NOT NULL,
    plaquette REAL NOT NULL,
    plaquette_deviation_pct REAL NOT NULL,
    validation_passed INTEGER NOT NULL CHECK(validation_passed IN (0, 1))
);

CREATE TABLE workflow_runs (
    log_file TEXT PRIMARY KEY,
    num_voxels INTEGER NOT NULL,
    num_replicas INTEGER NOT NULL,
    makespan_seconds REAL NOT NULL,
    fom REAL NOT NULL,
    final_loss REAL NOT NULL,
    validation_passed INTEGER NOT NULL CHECK(validation_passed IN (0, 1))
);

CREATE TABLE milc_scaling (
    nodes INTEGER PRIMARY KEY,
    step_time REAL NOT NULL,
    speedup REAL NOT NULL,
    parallel_efficiency REAL NOT NULL
);
