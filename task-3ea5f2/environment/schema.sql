-- ATS-5 SPARTA Benchmark Results Schema
-- Initialize with: sqlite3 /app/benchmark.db < /app/reference/schema.sql

CREATE TABLE IF NOT EXISTS runs (
    run_name TEXT PRIMARY KEY,
    num_nodes INTEGER NOT NULL,
    num_ranks INTEGER NOT NULL,
    wall_time REAL,
    num_stats_blocks INTEGER DEFAULT 1,
    fom REAL,
    manifest_nodes INTEGER,
    manifest_ranks INTEGER
);

CREATE TABLE IF NOT EXISTS scaling_models (
    model_name TEXT PRIMARY KEY,
    param1_name TEXT NOT NULL,
    param1_value REAL NOT NULL,
    param2_name TEXT,
    param2_value REAL,
    r_squared REAL NOT NULL,
    predicted_fom_256 REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_name TEXT,
    issue_type TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('data', 'script')),
    detail TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS scaling_summary AS
SELECT
    r.run_name,
    r.num_nodes,
    r.fom,
    r.manifest_nodes,
    CASE WHEN r.num_nodes != r.manifest_nodes THEN 'MISMATCH' ELSE 'OK' END AS manifest_status,
    CASE WHEN r.num_stats_blocks > 1 THEN 'RESTART' ELSE 'NORMAL' END AS run_status
FROM runs r
ORDER BY r.num_nodes;
