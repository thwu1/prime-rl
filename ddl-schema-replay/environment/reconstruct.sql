
-- Reconstruct the final schema state from the DDL history.
-- Parse each MySQL DDL statement from the ddl_history table
-- and populate the schema_state table below.

DROP TABLE IF EXISTS schema_state;
CREATE TABLE schema_state (
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    ordinal_position INT NOT NULL,
    data_type TEXT NOT NULL,
    is_nullable BOOLEAN NOT NULL,
    column_default TEXT,
    is_primary_key BOOLEAN NOT NULL,
    is_generated BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (table_name, column_name)
);

-- TODO: Implement DDL parsing logic to populate schema_state.
-- The ddl_history table contains 25 MySQL DDL statements in seq_id order.
-- Parse CREATE TABLE, ALTER TABLE, and DROP TABLE statements.
-- Track column metadata through all schema changes.
