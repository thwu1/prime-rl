CREATE TABLE IF NOT EXISTS configurations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    num_iterations INTEGER NOT NULL,
    coefficients TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matrices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    seed INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL REFERENCES configurations(id),
    matrix_id INTEGER NOT NULL REFERENCES matrices(id),
    orthogonality_error REAL NOT NULL,
    gram_matches_standard INTEGER NOT NULL,
    UNIQUE(config_id, matrix_id)
);

CREATE TABLE IF NOT EXISTS stability_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL REFERENCES configurations(id),
    num_restarts INTEGER NOT NULL,
    optimal_positions TEXT,
    stability_metric REAL NOT NULL,
    UNIQUE(config_id, num_restarts)
);
