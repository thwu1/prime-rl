CREATE TABLE IF NOT EXISTS results (
    case_name TEXT PRIMARY KEY,
    score INTEGER NOT NULL,
    status TEXT NOT NULL,
    solver_time_ms INTEGER,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE VIEW IF NOT EXISTS summary AS
SELECT
    COUNT(*) AS num_cases,
    CAST(AVG(score) AS INTEGER) AS avg_score,
    MIN(score) AS min_score,
    MAX(score) AS max_score,
    SUM(CASE WHEN status = 'OK' THEN 1 ELSE 0 END) AS valid_cases
FROM results;
