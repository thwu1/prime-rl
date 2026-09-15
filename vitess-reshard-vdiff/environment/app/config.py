"""Shard configuration for the Vitess-compatible migration system."""

import os

DATA_DIR = '/app/data'

# Source keyspace: 2 shards partitioned by hash vindex on workspace_id
SOURCE_SHARDS = {
    '-80': os.path.join(DATA_DIR, 'source_dash80.db'),
    '80-': os.path.join(DATA_DIR, 'source_80dash.db'),
}

# Target keyspace: 4 shards (result of resharding -80 and 80-)
TARGET_SHARDS = {
    '-40': os.path.join(DATA_DIR, 'target_dash40.db'),
    '40-80': os.path.join(DATA_DIR, 'target_40dash80.db'),
    '80-c0': os.path.join(DATA_DIR, 'target_80dashc0.db'),
    'c0-': os.path.join(DATA_DIR, 'target_c0dash.db'),
}

# Sharding key column present in all tables
SHARDING_KEY = 'workspace_id'

# Tables to migrate (ordered to respect foreign key dependencies)
TABLES = ['workspaces', 'users', 'channels', 'channel_members', 'thread_subscriptions']

# Primary key for each table
TABLE_PKS = {
    'workspaces': 'workspace_id',
    'users': 'user_id',
    'channels': 'channel_id',
    'channel_members': 'member_id',
    'thread_subscriptions': 'sub_id',
}
