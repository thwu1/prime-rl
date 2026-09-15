"""SQLite-backed trace logger for deterministic simulation.

Records simulation events to a SQLite database for post-hoc analysis.
Use ``sqlite3`` CLI or Python to query::

    sqlite3 /app/traces.db "SELECT * FROM events WHERE seed=42"
    sqlite3 /app/traces.db "SELECT node_id, store_json FROM node_states WHERE seed=0 ORDER BY sim_time DESC"
"""

import sqlite3
import json
import os


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_time REAL NOT NULL,
    seed INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    src_node INTEGER,
    dst_node INTEGER,
    detail TEXT,
    tag TEXT
);

CREATE TABLE IF NOT EXISTS node_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_time REAL NOT NULL,
    seed INTEGER NOT NULL,
    node_id INTEGER NOT NULL,
    term INTEGER NOT NULL,
    role TEXT NOT NULL,
    log_length INTEGER NOT NULL,
    commit_idx INTEGER NOT NULL,
    store_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_seed ON events(seed);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_states_seed ON node_states(seed);
CREATE INDEX IF NOT EXISTS idx_states_node ON node_states(seed, node_id);
"""


class TraceDB:
    """Append-only trace database for simulation analysis."""

    def __init__(self, path="/app/traces.db"):
        self._path = path
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def log_event(self, sim_time, seed, event_type, src=None, dst=None,
                  detail=None, tag=None):
        self._conn.execute(
            "INSERT INTO events(sim_time,seed,event_type,src_node,dst_node,"
            "detail,tag) VALUES(?,?,?,?,?,?,?)",
            (sim_time, seed, event_type, src, dst,
             json.dumps(detail) if detail else None, tag))

    def snapshot_node(self, sim_time, seed, node):
        """Record the current state of a Replica node."""
        self._conn.execute(
            "INSERT INTO node_states(sim_time,seed,node_id,term,role,"
            "log_length,commit_idx,store_json) VALUES(?,?,?,?,?,?,?,?)",
            (sim_time, seed, node.nid, node.term, node.role,
             len(node.log), node.commit_idx, json.dumps(node.store)))

    def flush(self):
        self._conn.commit()

    def close(self):
        self._conn.commit()
        self._conn.close()

    def query(self, sql, params=()):
        """Run a SQL query and return all rows."""
        return self._conn.execute(sql, params).fetchall()

    def clear_seed(self, seed):
        """Remove all data for a specific seed."""
        self._conn.execute("DELETE FROM events WHERE seed=?", (seed,))
        self._conn.execute("DELETE FROM node_states WHERE seed=?", (seed,))
        self._conn.commit()
