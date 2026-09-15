#!/usr/bin/env python3
"""Seed the sharded database with realistic Slack-like data.

Creates workspaces, users, channels, messages, and thread subscriptions
distributed across shards by workspace_id.  A JSON manifest of every
inserted row is saved to /app/data/manifest.json so that post-reshard
tests can verify data integrity without access to the original shard.
"""

import sys
sys.path.insert(0, "/app")

import os
import json
import random
from shard_manager import (
    ShardManager, init_shard_db, compute_shard_byte, DATA_DIR, TABLES
)

random.seed(42)


def main():
    # Initialise the two starting shards
    for shard in ["-80", "80-"]:
        init_shard_db(shard)

    mgr = ShardManager()
    manifest = {"rows": [], "original_shards": ["-80", "80-"]}

    ctr = {"user": 1, "channel": 1, "message": 1, "sub": 1}

    workspace_ids = list(range(1000, 1035))
    enterprise_ids = {1003, 1007, 1012, 1018, 1025, 1030}

    for ws_id in workspace_ids:
        is_ent = ws_id in enterprise_ids
        shard = mgr.route_query("workspaces", ws_id)
        conn = mgr.get_connection(shard)

        conn.execute(
            "INSERT INTO workspaces VALUES (?,?,?,?)",
            (ws_id, f"workspace_{ws_id}",
             "enterprise" if is_ent else "free", "2020-01-15"),
        )
        manifest["rows"].append(
            {"table": "workspaces", "pk": ws_id, "shard_key": ws_id}
        )

        # ── Users ───────────────────────────────────────────────────────
        n_users = random.randint(30, 55) if is_ent else random.randint(5, 14)
        user_ids = []
        for _ in range(n_users):
            uid = ctr["user"]; ctr["user"] += 1
            user_ids.append(uid)
            conn.execute(
                "INSERT INTO users VALUES (?,?,?,?,?,?)",
                (uid, ws_id, f"user_{uid}", f"u{uid}@ws{ws_id}.com",
                 1, "2020-02-01"),
            )
            manifest["rows"].append(
                {"table": "users", "pk": uid, "shard_key": ws_id}
            )

        # ── Channels ────────────────────────────────────────────────────
        n_channels = random.randint(12, 28) if is_ent else random.randint(3, 8)
        channel_ids = []
        for _ in range(n_channels):
            cid = ctr["channel"]; ctr["channel"] += 1
            channel_ids.append(cid)
            conn.execute(
                "INSERT INTO channels VALUES (?,?,?,?,?)",
                (cid, ws_id, f"channel_{cid}", 1, "2020-02-01"),
            )
            manifest["rows"].append(
                {"table": "channels", "pk": cid, "shard_key": ws_id}
            )

        # ── Messages (some are thread roots) ────────────────────────────
        thread_roots = []
        for cid in channel_ids:
            n_msg = random.randint(4, 12) if is_ent else random.randint(1, 4)
            for _ in range(n_msg):
                mid = ctr["message"]; ctr["message"] += 1
                uid = random.choice(user_ids)
                ts = f"ts_{mid}" if random.random() < 0.35 else None
                if ts:
                    thread_roots.append((cid, ts))
                conn.execute(
                    "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                    (mid, cid, ws_id, uid, ts, f"msg_{mid}", "2020-06-15"),
                )
                manifest["rows"].append(
                    {"table": "messages", "pk": mid, "shard_key": ws_id}
                )

        # ── Thread subscriptions ────────────────────────────────────────
        if thread_roots:
            for uid in user_ids:
                n_subs = random.randint(4, 12) if is_ent else random.randint(1, 3)
                chosen = random.sample(
                    thread_roots, min(n_subs, len(thread_roots))
                )
                for cid, ts in chosen:
                    sid = ctr["sub"]; ctr["sub"] += 1
                    conn.execute(
                        "INSERT INTO thread_subscriptions VALUES (?,?,?,?,?,?,?)",
                        (sid, uid, cid, ws_id, ts, 1, "2020-06-15"),
                    )
                    manifest["rows"].append(
                        {"table": "thread_subscriptions",
                         "pk": sid, "shard_key": ws_id}
                    )

        conn.commit()

    # ── Save manifest ───────────────────────────────────────────────────
    with open(os.path.join(DATA_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f)

    # ── Summary ─────────────────────────────────────────────────────────
    print("Seed summary:")
    for table in TABLES:
        total = sum(1 for r in manifest["rows"] if r["table"] == table)
        print(f"  {table}: {total} rows")

    shard_dist = {}
    for r in manifest["rows"]:
        bv = compute_shard_byte(r["shard_key"])
        s = "-80" if bv < 0x80 else "80-"
        shard_dist[s] = shard_dist.get(s, 0) + 1
    for s, c in sorted(shard_dist.items()):
        print(f"  shard {s}: {c} rows")

    mgr.close_all()
    print("Seed complete.")


if __name__ == "__main__":
    main()
