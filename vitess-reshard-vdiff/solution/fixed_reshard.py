"""
Vitess-compatible resharding implementation (complete).
Migrates data from source shards to target shards based on keyspace ID routing.
"""
import sqlite3
from config import SOURCE_SHARDS, TARGET_SHARDS, SHARDING_KEY, TABLES
from vindex import get_shard_for_value
from schema import SCHEMA_SQL


TARGET_SHARD_RANGES = [
    ("", "40"),
    ("40", "80"),
    ("80", "c0"),
    ("c0", ""),
]


def execute_reshard(source_shards=None, target_shards=None):
    """
    Execute the reshard operation: migrate data from source shards to target shards.

    For each table, reads all rows from all source shards, computes the target
    shard for each row based on its workspace_id keyspace ID, and inserts it
    into the correct target shard database.
    """
    if source_shards is None:
        source_shards = SOURCE_SHARDS
    if target_shards is None:
        target_shards = TARGET_SHARDS

    # Open target connections and initialize schema
    target_conns = {}
    for shard_name, db_path in target_shards.items():
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_SQL)
        # Clear any existing data for idempotency
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        target_conns[shard_name] = conn

    stats = {'tables': {}, 'success': False}

    try:
        for table in TABLES:
            source_rows = 0
            shard_dist = {}

            for src_path in source_shards.values():
                src_conn = sqlite3.connect(src_path)

                # Get column names and find the sharding key index
                cursor = src_conn.execute(f"PRAGMA table_info({table})")
                columns = [row[1] for row in cursor.fetchall()]
                ws_idx = columns.index(SHARDING_KEY)

                rows = src_conn.execute(f"SELECT * FROM {table}").fetchall()
                src_conn.close()
                source_rows += len(rows)

                for row in rows:
                    ws_id = row[ws_idx]
                    target_shard = get_shard_for_value(ws_id, TARGET_SHARD_RANGES)
                    shard_dist[target_shard] = shard_dist.get(target_shard, 0) + 1

                    placeholders = ','.join(['?'] * len(columns))
                    col_names = ','.join(columns)
                    target_conns[target_shard].execute(
                        f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                        list(row)
                    )

            # Commit after each table
            for conn in target_conns.values():
                conn.commit()

            target_rows = sum(shard_dist.values())
            stats['tables'][table] = {
                'source_rows': source_rows,
                'target_rows': target_rows,
                'shard_distribution': shard_dist,
            }

        stats['success'] = True
    finally:
        for conn in target_conns.values():
            conn.close()

    return stats
