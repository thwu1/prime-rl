-- PostgreSQL schema for the Polyomino Field Inference Pipeline.
-- Create database 'polyfield' and apply this schema.
--

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    case_id         INTEGER NOT NULL,
    n               INTEGER NOT NULL,
    m               INTEGER NOT NULL,
    epsilon         DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS queries (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id),
    query_type      TEXT NOT NULL CHECK(query_type IN ('drill', 'divine')),
    params_json     TEXT NOT NULL,
    result_value    INTEGER NOT NULL,
    query_cost      DOUBLE PRECISION NOT NULL,
    cumulative_cost DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    session_id      TEXT PRIMARY KEY REFERENCES sessions(session_id),
    case_id         INTEGER NOT NULL,
    num_cells       INTEGER NOT NULL,
    total_cost      DOUBLE PRECISION NOT NULL,
    correct         INTEGER NOT NULL CHECK(correct IN (0, 1)),
    precision_score DOUBLE PRECISION NOT NULL,
    recall_score    DOUBLE PRECISION NOT NULL,
    cells_json      TEXT NOT NULL
);
