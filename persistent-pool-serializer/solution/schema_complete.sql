-- Persistent Vector Snapshot Store - Complete Schema

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    root_node_id INTEGER,
    tail TEXT NOT NULL DEFAULT '[]',
    vec_size INTEGER NOT NULL DEFAULT 0,
    shift INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS nodes (
    node_id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_hash TEXT UNIQUE NOT NULL,
    is_leaf INTEGER NOT NULL,
    data TEXT NOT NULL
);
