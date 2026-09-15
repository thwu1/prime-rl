"""
Vitess-style shard manager for SQLite-based shard simulation.

Provides hash-based keyspace ID routing, connection management, and query
execution across a set of shards.  Each shard is a separate SQLite database
file stored under DATA_DIR.

Shard naming follows Vitess conventions:
    '-80'   -> keyspace bytes [0x00, 0x80)
    '80-'   -> keyspace bytes [0x80, 0x100)
    '40-80' -> keyspace bytes [0x40, 0x80)
"""

import sqlite3
import hashlib
import os
import json
from typing import List, Dict, Any, Optional, Tuple

DATA_DIR = "/app/data"
VSCHEMA_PATH = "/app/vschema.json"

# ── Schema ──────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    plan TEXT DEFAULT 'free',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    email TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    is_public INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    thread_ts TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_subscriptions (
    sub_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    thread_ts TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_workspace ON users(workspace_id);
CREATE INDEX IF NOT EXISTS idx_channels_workspace ON channels(workspace_id);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id);
CREATE INDEX IF NOT EXISTS idx_messages_workspace ON messages(workspace_id);
CREATE INDEX IF NOT EXISTS idx_thread_subs_user ON thread_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_thread_subs_channel ON thread_subscriptions(channel_id);
CREATE INDEX IF NOT EXISTS idx_thread_subs_workspace ON thread_subscriptions(workspace_id);
CREATE INDEX IF NOT EXISTS idx_thread_subs_user_channel ON thread_subscriptions(user_id, channel_id);
"""

TABLES = ["workspaces", "users", "channels", "messages", "thread_subscriptions"]

TABLE_SHARD_KEY = {
    "workspaces": "workspace_id",
    "users": "workspace_id",
    "channels": "workspace_id",
    "messages": "workspace_id",
    "thread_subscriptions": "workspace_id",
}

TABLE_PRIMARY_KEY = {
    "workspaces": "workspace_id",
    "users": "user_id",
    "channels": "channel_id",
    "messages": "message_id",
    "thread_subscriptions": "sub_id",
}

# ── Hashing / Routing ──────────────────────────────────────────────────────

def compute_shard_byte(key_value: int) -> int:
    """Return the routing byte (0-255) for *key_value*.

    Uses the first byte of the MD5 digest of the string representation.
    This mirrors how Vitess computes a keyspace ID and then routes by
    the most-significant byte.
    """
    h = hashlib.md5(str(key_value).encode()).hexdigest()
    return int(h[:2], 16)


def parse_shard_range(shard_name: str) -> Tuple[int, int]:
    """Parse a Vitess-style shard name into an integer byte range [start, end).

    Examples
    --------
    >>> parse_shard_range('-80')
    (0, 128)
    >>> parse_shard_range('80-')
    (128, 256)
    >>> parse_shard_range('40-80')
    (64, 128)
    """
    if shard_name == "-":
        return (0, 256)
    if shard_name.startswith("-"):
        return (0, int(shard_name[1:], 16))
    if shard_name.endswith("-"):
        return (int(shard_name[:-1], 16), 256)
    parts = shard_name.split("-")
    return (int(parts[0], 16), int(parts[1], 16))


def route_to_shard(key_value: int, shard_names: List[str]) -> str:
    """Route *key_value* to the matching shard name."""
    byte_val = compute_shard_byte(key_value)
    for sname in shard_names:
        start, end = parse_shard_range(sname)
        if start <= byte_val < end:
            return sname
    raise ValueError(
        f"No shard found for key={key_value}, byte=0x{byte_val:02x}"
    )


# ── File paths ──────────────────────────────────────────────────────────────

def shard_db_path(shard_name: str) -> str:
    """Map a Vitess shard name to a database file path.

    '-80'   -> /app/data/shard_0_80.db
    '80-'   -> /app/data/shard_80_ff.db
    '40-80' -> /app/data/shard_40_80.db
    """
    if shard_name.startswith("-"):
        return os.path.join(DATA_DIR, f"shard_0_{shard_name[1:]}.db")
    if shard_name.endswith("-"):
        return os.path.join(DATA_DIR, f"shard_{shard_name[:-1]}_ff.db")
    parts = shard_name.split("-")
    return os.path.join(DATA_DIR, f"shard_{parts[0]}_{parts[1]}.db")


# ── VSchema helpers ─────────────────────────────────────────────────────────

def load_vschema() -> dict:
    with open(VSCHEMA_PATH) as f:
        return json.load(f)


def save_vschema(vschema: dict) -> None:
    with open(VSCHEMA_PATH, "w") as f:
        json.dump(vschema, f, indent=2)


# ── Shard initialisation ───────────────────────────────────────────────────

def init_shard_db(shard_name: str) -> None:
    """Create (or re-create) the SQLite database for *shard_name*."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(shard_db_path(shard_name))
    conn.executescript(SCHEMA_SQL)
    conn.close()


# ── Connection wrapper ──────────────────────────────────────────────────────

class ShardConnection:
    """Thin wrapper around a SQLite connection to a single shard."""

    def __init__(self, shard_name: str):
        self.shard_name = shard_name
        self.db_path = shard_db_path(shard_name)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(query, params)

    def executemany(self, query: str, params_list: list) -> None:
        self.conn.executemany(query, params_list)

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def fetchall(self, query: str, params: tuple = ()) -> List[Dict]:
        cursor = self.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def fetchone(self, query: str, params: tuple = ()) -> Optional[Dict]:
        cursor = self.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None


# ── Shard manager ───────────────────────────────────────────────────────────

class ShardManager:
    """High-level manager: routes queries and manages connections."""

    def __init__(self):
        self.vschema = load_vschema()
        self.shard_names: List[str] = self.vschema.get("shards", ["-80", "80-"])
        self._connections: Dict[str, ShardConnection] = {}

    def get_connection(self, shard_name: str) -> ShardConnection:
        if shard_name not in self._connections:
            self._connections[shard_name] = ShardConnection(shard_name)
        return self._connections[shard_name]

    def route_query(self, table: str, shard_key_value: int) -> str:
        """Determine which shard holds rows for *shard_key_value*."""
        return route_to_shard(shard_key_value, self.shard_names)

    def insert_row(self, table: str, data: Dict[str, Any]) -> None:
        shard_key_col = TABLE_SHARD_KEY[table]
        shard_name = self.route_query(table, data[shard_key_col])
        conn = self.get_connection(shard_name)
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data])
        conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            tuple(data.values()),
        )
        conn.commit()

    def query_shard(
        self, shard_name: str, query: str, params: tuple = ()
    ) -> List[Dict]:
        return self.get_connection(shard_name).fetchall(query, params)

    def scatter_query(self, query: str, params: tuple = ()) -> List[Dict]:
        """Execute *query* on every shard and concatenate results."""
        results: List[Dict] = []
        for sname in self.shard_names:
            results.extend(self.query_shard(sname, query, params))
        return results

    def execute_on_shard(
        self, shard_name: str, query: str, params: tuple = ()
    ) -> None:
        conn = self.get_connection(shard_name)
        conn.execute(query, params)
        conn.commit()

    def close_all(self) -> None:
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()
