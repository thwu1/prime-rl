-- Schema reference for /app/workloads.db
-- The workloads table is pre-populated. The evaluations and recommendations
-- tables are empty and must be populated by the agent.

CREATE TABLE workloads (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    eigenvalues TEXT NOT NULL,     -- JSON array of singular values (floats)
    perturbation REAL NOT NULL,    -- negative perturbation simulating float error
    max_restarts INTEGER NOT NULL  -- maximum number of restart positions to evaluate
);

CREATE TABLE evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workload_id INTEGER NOT NULL,
    coefficient_set TEXT NOT NULL CHECK(coefficient_set IN ('CLASSICAL', 'YOU')),
    num_restarts INTEGER NOT NULL,
    restart_positions TEXT NOT NULL,  -- JSON array of restart iteration indices
    stability_metric REAL NOT NULL,
    FOREIGN KEY (workload_id) REFERENCES workloads(id)
);

CREATE TABLE recommendations (
    workload_id INTEGER PRIMARY KEY,
    best_coefficient_set TEXT NOT NULL,
    best_num_restarts INTEGER NOT NULL,
    best_restart_positions TEXT NOT NULL,  -- JSON array
    best_stability_metric REAL NOT NULL,
    FOREIGN KEY (workload_id) REFERENCES workloads(id)
);
