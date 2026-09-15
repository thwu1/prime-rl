CREATE TABLE IF NOT EXISTS circuits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    n_qubits INTEGER NOT NULL,
    n_gates INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS amplitudes (
    circuit_id INTEGER NOT NULL REFERENCES circuits(id),
    basis_state INTEGER NOT NULL,
    real_part REAL NOT NULL,
    imag_part REAL NOT NULL,
    probability REAL NOT NULL,
    PRIMARY KEY (circuit_id, basis_state)
);
