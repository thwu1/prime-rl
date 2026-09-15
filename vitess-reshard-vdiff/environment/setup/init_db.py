#!/usr/bin/env python3
"""Initialize shard databases with deterministic test data."""
import xxhash
import struct
import sqlite3
import random
import os

random.seed(42)

DATA_DIR = '/app/data'
os.makedirs(DATA_DIR, exist_ok=True)

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


def compute_keyspace_id(value):
    """Correct Vitess xxhash64 keyspace ID computation."""
    packed = struct.pack('>Q', value)
    hash_val = xxhash.xxh64(packed).intdigest()
    return struct.pack('>Q', hash_val)


def get_source_shard(workspace_id):
    """Determine source shard for a workspace using 2-shard partition."""
    ksid = compute_keyspace_id(workspace_id)
    ksid_int = struct.unpack('>Q', ksid)[0]
    if ksid_int < 0x8000000000000000:
        return '-80'
    else:
        return '80-'


# Database file paths
source_dbs = {
    '-80': os.path.join(DATA_DIR, 'source_dash80.db'),
    '80-': os.path.join(DATA_DIR, 'source_80dash.db'),
}

target_dbs = {
    '-40': os.path.join(DATA_DIR, 'target_dash40.db'),
    '40-80': os.path.join(DATA_DIR, 'target_40dash80.db'),
    '80-c0': os.path.join(DATA_DIR, 'target_80dashc0.db'),
    'c0-': os.path.join(DATA_DIR, 'target_c0dash.db'),
}

# Initialize all databases with schema
for db_path in list(source_dbs.values()) + list(target_dbs.values()):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.close()

# Open source connections
source_conns = {}
for shard_name, db_path in source_dbs.items():
    source_conns[shard_name] = sqlite3.connect(db_path)

# Generate 40 workspaces
workspace_ids = list(range(1000, 1040))
workspace_shards = {}
for wid in workspace_ids:
    shard = get_source_shard(wid)
    workspace_shards[wid] = shard
    source_conns[shard].execute(
        "INSERT INTO workspaces (workspace_id, name) VALUES (?, ?)",
        (wid, f"workspace_{wid}")
    )

# Generate 5 users per workspace (200 total)
user_id_counter = 2000
user_workspace = {}
for wid in workspace_ids:
    shard = workspace_shards[wid]
    for i in range(5):
        source_conns[shard].execute(
            "INSERT INTO users (user_id, workspace_id, username, status) VALUES (?, ?, ?, 'active')",
            (user_id_counter, wid, f"user_{user_id_counter}")
        )
        user_workspace[user_id_counter] = wid
        user_id_counter += 1

# Generate 3 channels per workspace (120 total)
channel_id_counter = 3000
channel_workspace = {}
for wid in workspace_ids:
    shard = workspace_shards[wid]
    for i in range(3):
        source_conns[shard].execute(
            "INSERT INTO channels (channel_id, workspace_id, name) VALUES (?, ?, ?)",
            (channel_id_counter, wid, f"channel_{channel_id_counter}")
        )
        channel_workspace[channel_id_counter] = wid
        channel_id_counter += 1

# Build channel lookup by workspace
channels_by_workspace = {}
for cid, wid in channel_workspace.items():
    channels_by_workspace.setdefault(wid, []).append(cid)

# Generate channel memberships: each user joins 2-3 channels in their workspace
member_id_counter = 4000
user_channels = {}
for uid, wid in user_workspace.items():
    ws_channels = channels_by_workspace[wid]
    num_join = min(len(ws_channels), random.randint(2, 3))
    joined = sorted(random.sample(ws_channels, num_join))
    user_channels[uid] = joined
    shard = workspace_shards[wid]
    for cid in joined:
        source_conns[shard].execute(
            "INSERT INTO channel_members (member_id, channel_id, user_id, workspace_id) VALUES (?, ?, ?, ?)",
            (member_id_counter, cid, uid, wid)
        )
        member_id_counter += 1

# Generate thread subscriptions: 2-4 per user-channel pair
sub_id_counter = 5000
for uid, channels in user_channels.items():
    wid = user_workspace[uid]
    shard = workspace_shards[wid]
    for cid in channels:
        num_subs = random.randint(2, 4)
        for _ in range(num_subs):
            thread_ts = random.randint(1700000000, 1710000000)
            source_conns[shard].execute(
                "INSERT INTO thread_subscriptions "
                "(sub_id, channel_id, thread_ts, user_id, workspace_id, status) "
                "VALUES (?, ?, ?, ?, ?, 'active')",
                (sub_id_counter, cid, thread_ts, uid, wid)
            )
            sub_id_counter += 1

# Commit and close
for conn in source_conns.values():
    conn.commit()
    conn.close()

# Print statistics
print("Database initialization complete.")
print(f"Workspaces: {len(workspace_ids)}")
print(f"Users: {user_id_counter - 2000}")
print(f"Channels: {channel_id_counter - 3000}")
print(f"Channel members: {member_id_counter - 4000}")
print(f"Thread subscriptions: {sub_id_counter - 5000}")

for shard_name, db_path in source_dbs.items():
    conn = sqlite3.connect(db_path)
    ws_count = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    sub_count = conn.execute("SELECT COUNT(*) FROM thread_subscriptions").fetchone()[0]
    print(f"Shard {shard_name}: {ws_count} workspaces, {user_count} users, {sub_count} subscriptions")
    conn.close()
