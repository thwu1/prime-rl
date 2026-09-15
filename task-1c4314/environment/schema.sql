-- Required SQLite schema for DERP forensic audit database.
-- All tables must be created with these exact column names and types.

CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY,
    conn_id INTEGER NOT NULL,
    direction INTEGER NOT NULL,
    frame_type INTEGER NOT NULL,
    frame_type_name TEXT NOT NULL,
    payload_len INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS connections (
    conn_id INTEGER PRIMARY KEY,
    client_key_hex TEXT,
    is_mesh_peer INTEGER NOT NULL DEFAULT 0,
    handshake_complete INTEGER NOT NULL DEFAULT 0,
    frame_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS routing_events (
    id INTEGER PRIMARY KEY,
    frame_id INTEGER NOT NULL,
    src_key_hex TEXT,
    dst_key_hex TEXT,
    data_bytes INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('send', 'recv', 'forward')),
    FOREIGN KEY (frame_id) REFERENCES frames(id)
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY,
    frame_id INTEGER NOT NULL,
    anomaly_type TEXT NOT NULL,
    conn_id INTEGER,
    description TEXT NOT NULL,
    FOREIGN KEY (frame_id) REFERENCES frames(id)
);
