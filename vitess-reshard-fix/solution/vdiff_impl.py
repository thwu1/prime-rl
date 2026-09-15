#!/usr/bin/env python3
"""
VDiff — verify post-reshard data consistency.

Reads the data manifest produced at seed time and confirms that every row
which originally lived in the source shard now exists in exactly one of the
target shards at the correct routing position.

Exit 0 on success, non-zero on any discrepancy.
"""

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, "/app")
from shard_manager import (
    DATA_DIR, TABLES, TABLE_PRIMARY_KEY,
    compute_shard_byte, parse_shard_range, shard_db_path,
)


def vdiff(source_shard: str, target_shards: list[str]) -> bool:
    manifest_path = os.path.join(DATA_DIR, "manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    src_lo, src_hi = parse_shard_range(source_shard)
    target_ranges = {t: parse_shard_range(t) for t in target_shards}

    errors: list[str] = []
    verified = 0

    for table in TABLES:
        pk_col = TABLE_PRIMARY_KEY[table]

        # rows that belonged to the source shard
        expected = [
            r for r in manifest["rows"]
            if r["table"] == table
            and src_lo <= compute_shard_byte(r["shard_key"]) < src_hi
        ]

        for row_info in expected:
            bv = compute_shard_byte(row_info["shard_key"])

            target = None
            for t, (lo, hi) in target_ranges.items():
                if lo <= bv < hi:
                    target = t
                    break

            if target is None:
                errors.append(
                    f"No target for {table} pk={row_info['pk']} "
                    f"byte=0x{bv:02x}"
                )
                continue

            db_path = shard_db_path(target)
            if not os.path.exists(db_path):
                errors.append(f"Target DB missing: {db_path}")
                continue

            conn = sqlite3.connect(db_path)
            cnt = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {pk_col} = ?",
                (row_info["pk"],),
            ).fetchone()[0]
            conn.close()

            if cnt == 0:
                errors.append(
                    f"MISSING: {table} pk={row_info['pk']} not in {target}"
                )
            elif cnt > 1:
                errors.append(
                    f"DUPLICATE: {table} pk={row_info['pk']} x{cnt} in {target}"
                )
            else:
                verified += 1

    if errors:
        print(f"VDiff FAILED — {len(errors)} errors, {verified} OK")
        for e in errors[:25]:
            print(f"  {e}")
        if len(errors) > 25:
            print(f"  … and {len(errors) - 25} more")
        return False

    print(f"VDiff PASSED — {verified} rows verified across {target_shards}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VDiff consistency check")
    parser.add_argument("--source", required=True)
    parser.add_argument("--targets", required=True)
    args = parser.parse_args()

    tgts = [s.strip() for s in args.targets.split(",")]
    ok = vdiff(args.source, tgts)
    sys.exit(0 if ok else 1)
