"""Database schema definitions for all shard databases."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT DEFAULT '2024-01-01 00:00:00'
);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'deactivated'))
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT DEFAULT '2024-01-01 00:00:00'
);

CREATE TABLE IF NOT EXISTS channel_members (
    member_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    joined_at TEXT DEFAULT '2024-01-01 00:00:00',
    UNIQUE(channel_id, user_id)
);

CREATE TABLE IF NOT EXISTS thread_subscriptions (
    sub_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    thread_ts INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'inactive'))
);
"""
