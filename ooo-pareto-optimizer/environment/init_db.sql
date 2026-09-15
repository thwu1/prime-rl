-- Workload metadata and experiment tracking schema for archsim

CREATE TABLE IF NOT EXISTS workloads (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    workload_type TEXT NOT NULL,
    priority_weight REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    width INTEGER NOT NULL,
    rob_size INTEGER NOT NULL,
    num_int_regs INTEGER NOT NULL,
    num_fp_regs INTEGER NOT NULL,
    workload TEXT NOT NULL REFERENCES workloads(name),
    paired_workload TEXT DEFAULT NULL REFERENCES workloads(name),
    ipc REAL NOT NULL,
    area INTEGER NOT NULL,
    power_watts REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_experiments_config
    ON experiments(width, rob_size, num_int_regs, num_fp_regs);
CREATE INDEX IF NOT EXISTS idx_experiments_workload
    ON experiments(workload);

INSERT INTO workloads VALUES ('matmul', 'Dense matrix multiplication', 'compute', 2.0);
INSERT INTO workloads VALUES ('bfs', 'Breadth-first search on graph', 'memory', 1.5);
INSERT INTO workloads VALUES ('sort', 'Comparison-based sorting', 'branch', 1.0);
INSERT INTO workloads VALUES ('queens', 'N-Queens backtracking solver', 'branch', 0.8);
INSERT INTO workloads VALUES ('stream', 'Streaming integer array processing', 'memory', 1.2);
INSERT INTO workloads VALUES ('crypto', 'Cryptographic hash computation', 'mixed', 1.8);
INSERT INTO workloads VALUES ('fft', 'Fast Fourier Transform', 'compute', 1.5);
INSERT INTO workloads VALUES ('lzma', 'LZMA compression', 'mixed', 1.0);
