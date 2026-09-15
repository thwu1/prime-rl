-- Migration 001: Initial feature metadata schema
-- Applied: 2024-03-15
--
-- Creates the feature_columns table that stores metadata about
-- features used by the bot management ML model. Analogous to
-- ClickHouse's system.columns table.
--
-- Initially, only the 'default' schema is populated.
-- The 'default' schema corresponds to the distributed tables
-- that aggregate data across all shards of the cluster.

CREATE TABLE IF NOT EXISTS feature_columns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prefixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cidr TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    pending_delete INTEGER DEFAULT 0,
    service_binding TEXT,
    advertised INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS service_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prefix_id INTEGER NOT NULL,
    service_type TEXT NOT NULL,
    config TEXT,
    FOREIGN KEY (prefix_id) REFERENCES prefixes(id)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
