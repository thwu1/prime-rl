-- Test database setup: creates tables with varying bloat levels

CREATE EXTENSION IF NOT EXISTS pgstattuple;

------------------------------------------------------------
-- Table 1: Clean table, no modifications after insert
------------------------------------------------------------
CREATE TABLE test_minimal (
    id BIGINT NOT NULL,
    a INTEGER NOT NULL,
    b INTEGER NOT NULL
);

INSERT INTO test_minimal
SELECT i, (i * 7) % 10000, (i * 13) % 1000
FROM generate_series(1, 10000) i;

CREATE INDEX idx_minimal_a ON test_minimal(a);

------------------------------------------------------------
-- Table 2: Moderate bloat from updates, with nullable columns
------------------------------------------------------------
CREATE TABLE test_moderate (
    id INTEGER NOT NULL,
    name VARCHAR(50),
    val NUMERIC(10,2),
    active BOOLEAN,
    ts TIMESTAMP NOT NULL
);

INSERT INTO test_moderate
SELECT
    i,
    'name_' || lpad(i::text, 6, '0'),
    CASE WHEN i % 5 = 0 THEN NULL ELSE (i % 1000)::numeric(10,2) END,
    CASE WHEN i % 7 = 0 THEN NULL ELSE (i % 2 = 0) END,
    '2024-01-01 00:00:00'::timestamp + (i * interval '1 second')
FROM generate_series(1, 30000) i;

CREATE INDEX idx_moderate_name ON test_moderate(name);
CREATE INDEX idx_moderate_val ON test_moderate(val);

------------------------------------------------------------
-- Table 3: Heavy bloat from updates + deletes
------------------------------------------------------------
CREATE TABLE test_heavy (
    id SERIAL PRIMARY KEY,
    category VARCHAR(30) NOT NULL,
    data1 VARCHAR(100) NOT NULL,
    counter INTEGER NOT NULL DEFAULT 0
);

INSERT INTO test_heavy (category, data1, counter)
SELECT
    'cat_' || (i % 10),
    'data_' || lpad(i::text, 8, '0'),
    i
FROM generate_series(1, 50000) i;

CREATE INDEX idx_heavy_category ON test_heavy(category);
CREATE INDEX idx_heavy_counter ON test_heavy(counter);

------------------------------------------------------------
-- Create bloat via DML (no VACUUM to preserve dead tuples)
------------------------------------------------------------

-- Moderate bloat: update ~40% of test_moderate (where val IS NOT NULL)
UPDATE test_moderate SET val = val + 1 WHERE id % 2 = 0 AND val IS NOT NULL;

-- Heavy bloat: update 50% of test_heavy (indexed column changes) + delete 33%
UPDATE test_heavy SET category = 'upd_' || category, counter = counter + 1 WHERE id % 2 = 0;
DELETE FROM test_heavy WHERE id % 3 = 0;

------------------------------------------------------------
-- Analyze all tables to update statistics (but NOT vacuum)
------------------------------------------------------------
ANALYZE test_minimal;
ANALYZE test_moderate;
ANALYZE test_heavy;
