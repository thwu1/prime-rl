CREATE TABLE hardware (
    id INTEGER PRIMARY KEY,
    architecture TEXT NOT NULL,
    physical_error_rate REAL NOT NULL,
    surface_code_cycle_time_us REAL NOT NULL,
    threshold_error_rate REAL NOT NULL
);

CREATE TABLE algorithms (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    logical_qubits INTEGER NOT NULL,
    t_count INTEGER NOT NULL,
    measurement_depth INTEGER NOT NULL,
    rotation_count INTEGER NOT NULL,
    rotation_precision REAL NOT NULL,
    target_error REAL NOT NULL
);

INSERT INTO hardware VALUES (1, 'superconducting_v2', 0.001, 1.0, 0.01);

INSERT INTO algorithms VALUES (1, 'small_qpe', 10, 10000, 500, 200, 1e-6, 0.01);
INSERT INTO algorithms VALUES (2, 'medium_chem', 100, 10000000, 10000, 5000, 1e-10, 0.01);
INSERT INTO algorithms VALUES (3, 'large_factoring', 2000, 1000000000, 100000, 0, 0.0, 0.01);
