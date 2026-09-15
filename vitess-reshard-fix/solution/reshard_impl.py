#!/usr/bin/env python3
"""
Reshard tool — splits a Vitess-style shard into two sub-shards.

Reads every row from the source shard database, recomputes the routing byte
for each row's workspace_id, and inserts the row into the correct target
shard.  After successful migration the source database file is removed.
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, "/app")
from shard_manager import (
    TABLES, TABLE_SHARD_KEY,
    compute_shard_byte, init_shard_db, parse_shard_range, shard_db_path,
)


def reshard(source_shard: str, target_shards: list[str]) -> bool:
    src_path = shard_db_path(source_shard)
    if not os.path.exists(src_path):
        print(f"ERROR: source shard {source_shard} not found ({src_path})")
        return False

    # Create target databases
    for t in target_shards:
        init_shard_db(t)

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row

    targets = {t: sqlite3.connect(shard_db_path(t)) for t in target_shards}
    target_ranges = {t: parse_shard_range(t) for t in target_shards}

    for table in TABLES:
        shard_key_col = TABLE_SHARD_KEY[table]
        cursor = src.execute(f"SELECT * FROM {table}")
        col_names = [d[0] for d in cursor.description]
        placeholders = ",".join(["?"] * len(col_names))
        insert_sql = (
            f"INSERT INTO {table} ({','.join(col_names)}) "
            f"VALUES ({placeholders})"
        )

        count = 0
        for row in cursor:
            row_dict = dict(row)
            byte_val = compute_shard_byte(row_dict[shard_key_col])

            target = None
            for t, (lo, hi) in target_ranges.items():
                if lo <= byte_val < hi:
                    target = t
                    break

            if target is None:
                print(
                    f"ERROR: no target for {table} "
                    f"key={row_dict[shard_key_col]} byte=0x{byte_val:02x}"
                )
                return False

            targets[target].execute(
                insert_sql, tuple(row_dict[c] for c in col_names)
            )
            count += 1

        print(f"  {table}: {count} rows migrated")

    # Commit and close targets
    for conn in targets.values():
        conn.commit()
        conn.close()
    src.close()

    # Remove original shard
    os.remove(src_path)
    print(f"Removed source shard {source_shard} ({src_path})")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reshard a Vitess shard")
    parser.add_argument("--source-shard", default="-80")
    parser.add_argument("--target-shards", default="-40,40-80")
    args = parser.parse_args()

    tgts = [s.strip() for s in args.target_shards.split(",")]
    print(f"Resharding {args.source_shard} -> {tgts}")
    ok = reshard(args.source_shard, tgts)
    sys.exit(0 if ok else 1)
