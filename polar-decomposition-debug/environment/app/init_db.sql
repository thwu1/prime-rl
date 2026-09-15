CREATE TABLE IF NOT EXISTS workloads (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    eigenvalues TEXT NOT NULL,
    perturbation REAL NOT NULL,
    max_restarts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workload_id INTEGER NOT NULL,
    coefficient_set TEXT NOT NULL CHECK(coefficient_set IN ('CLASSICAL', 'YOU')),
    num_restarts INTEGER NOT NULL,
    restart_positions TEXT NOT NULL,
    stability_metric REAL NOT NULL,
    FOREIGN KEY (workload_id) REFERENCES workloads(id)
);

CREATE TABLE IF NOT EXISTS recommendations (
    workload_id INTEGER PRIMARY KEY,
    best_coefficient_set TEXT NOT NULL,
    best_num_restarts INTEGER NOT NULL,
    best_restart_positions TEXT NOT NULL,
    best_stability_metric REAL NOT NULL,
    FOREIGN KEY (workload_id) REFERENCES workloads(id)
);

INSERT INTO workloads (id, name, eigenvalues, perturbation, max_restarts) VALUES
    (1, 'low_rank_wide', '[0.04, 0.06, 0.10, 0.15, 0.20]', -0.0001, 2),
    (2, 'uniform_spread', '[0.1, 0.3, 0.5, 0.7, 0.9]', -0.00005, 2),
    (3, 'clustered_high', '[0.70, 0.75, 0.80, 0.85, 0.90]', -0.001, 1),
    (4, 'sparse_extreme', '[0.01, 0.05, 0.50, 0.95, 0.99]', -0.0002, 2);
