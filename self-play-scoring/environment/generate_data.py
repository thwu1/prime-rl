#!/usr/bin/env python3
"""Generate deterministic KVCache state database and workload trace.
"""
import sqlite3
import json
import os

DB_PATH = "/app/cache_state.db"
TRACE_PATH = "/app/upcoming_requests.json"
CONFIG_PATH = "/app/config.json"

NOW = 1700000000000  # Current epoch ms
ZOMBIE_TIMEOUT = 600000  # 10 min in ms
SOFT_PIN_TTL = 1800000  # 30 min in ms
BLOCK_SIZE = 512

NODES = [
    ("p0", "prefill", 200),
    ("p1", "prefill", 200),
    ("p2", "prefill", 200),
    ("p3", "prefill", 200),
    ("d0", "decode", 100),
    ("d1", "decode", 100),
]


def create_tables(c):
    c.executescript("""
    CREATE TABLE nodes (
        node_id TEXT PRIMARY KEY,
        node_type TEXT NOT NULL,
        capacity_blocks INTEGER NOT NULL
    );
    CREATE TABLE blocks (
        block_id TEXT PRIMARY KEY,
        hash_id INTEGER NOT NULL,
        node_id TEXT NOT NULL,
        size_tokens INTEGER NOT NULL DEFAULT 512,
        created_at INTEGER NOT NULL,
        last_accessed INTEGER NOT NULL,
        pin_type TEXT NOT NULL DEFAULT 'none',
        status TEXT NOT NULL DEFAULT 'complete',
        replica_group TEXT,
        put_start_time INTEGER
    );
    CREATE TABLE prefix_chains (
        hash_id INTEGER PRIMARY KEY,
        parent_hash_id INTEGER,
        token_offset INTEGER NOT NULL,
        content_hash TEXT NOT NULL
    );
    CREATE TABLE operations_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        operation TEXT NOT NULL,
        block_id TEXT,
        node_id TEXT,
        status TEXT NOT NULL,
        error_msg TEXT,
        latency_ms REAL
    );
    CREATE INDEX idx_blocks_node ON blocks(node_id);
    CREATE INDEX idx_blocks_hash ON blocks(hash_id);
    CREATE INDEX idx_blocks_status ON blocks(status);
    CREATE INDEX idx_blocks_pin ON blocks(pin_type);
    CREATE INDEX idx_ops_ts ON operations_log(timestamp);
    """)


def main():
    os.makedirs("/app", exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    create_tables(c)

    # Insert nodes
    for nid, ntype, cap in NODES:
        c.execute("INSERT INTO nodes VALUES (?,?,?)", (nid, ntype, cap))

    # ---- Prefix chains: 30 sessions ----
    hash_id = 0
    sessions = []
    for s in range(30):
        depth = 5 + (s * 3) % 16
        parent = None
        chain = []
        for d in range(depth):
            c.execute("INSERT INTO prefix_chains VALUES (?,?,?,?)",
                      (hash_id, parent, d * BLOCK_SIZE, f"s{s}b{d}"))
            chain.append(hash_id)
            parent = hash_id
            hash_id += 1
        sessions.append(chain)

    # Orphaned prefix chains (parent_hash_id doesn't exist)
    for i in range(12):
        fake_parent = 90000 + i
        c.execute("INSERT INTO prefix_chains VALUES (?,?,?,?)",
                  (hash_id, fake_parent, i * BLOCK_SIZE, f"orphan{i}"))
        hash_id += 1

    # ---- Place session blocks across nodes ----
    block_id = 0

    def bid():
        nonlocal block_id
        b = f"blk_{block_id:05d}"
        block_id += 1
        return b

    for s in range(30):
        if s < 10:
            primary = "p0"
        elif s < 20:
            primary = "p1"
        else:
            primary = None  # spread

        chain = sessions[s]
        for idx, hid in enumerate(chain):
            if s < 20:
                r10 = idx % 10
                if r10 < 7:
                    node = primary
                elif r10 == 7:
                    node = "p0" if primary == "p1" else "p1"
                elif r10 == 8:
                    node = "p2"
                else:
                    node = "p3"
            else:
                node = ["p0", "p1", "p2", "p3"][idx % 4]

            age = 120000 + (s * 50000 + idx * 30000) % 3000000
            created = NOW - age
            last_acc = created + age // 3

            c.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (bid(), hid, node, BLOCK_SIZE, created, last_acc,
                       "none", "complete", f"rg_{hid}", None))

    # ---- Duplicate replicas on SAME node (wasteful) ----
    dup_sessions = [0, 1, 2, 5, 10, 11, 12, 15]
    for s in dup_sessions:
        primary = "p0" if s < 10 else "p1"
        chain = sessions[s]
        for hid in chain[:3]:
            for _ in range(2):
                c.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (bid(), hid, primary, BLOCK_SIZE,
                           NOW - 500000, NOW - 400000,
                           "none", "complete", f"rg_{hid}", None))

    # ---- Zombie blocks (status=init, old put_start_time) ----
    zombie_pattern = ["p0", "p0", "p1", "p1", "p1"]
    for i in range(35):
        node = zombie_pattern[i % 5]
        zhash = 50000 + i
        put_time = NOW - ZOMBIE_TIMEOUT - 60000 - i * 30000
        c.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (bid(), zhash, node, BLOCK_SIZE, put_time, put_time,
                   "none", "init", None, put_time))

    # Recent init blocks (NOT zombies -- put_start within timeout)
    for i in range(5):
        node = "p0"
        rhash = 60000 + i
        put_time = NOW - 30000 - i * 5000
        c.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (bid(), rhash, node, BLOCK_SIZE, put_time, put_time,
                   "none", "init", None, put_time))

    # ---- Expired soft-pinned blocks ----
    for i in range(25):
        node = ["p0", "p1", "p2", "p3"][i % 4]
        sphash = 70000 + i
        old_time = NOW - SOFT_PIN_TTL - 120000 - i * 60000
        c.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (bid(), sphash, node, BLOCK_SIZE, old_time, old_time,
                   "soft", "complete", f"rg_{sphash}", None))

    # Active soft-pinned blocks (NOT expired)
    for i in range(10):
        node = ["p0", "p1", "p2", "p3"][i % 4]
        ashash = 71000 + i
        recent = NOW - 300000 - i * 10000
        c.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (bid(), ashash, node, BLOCK_SIZE, recent, recent,
                   "soft", "complete", f"rg_{ashash}", None))

    # ---- Hard-pinned blocks (must NEVER be evicted) ----
    for i in range(8):
        node = ["p0", "p1", "p2", "p3"][i % 4]
        hphash = 80000 + i
        c.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (bid(), hphash, node, BLOCK_SIZE,
                   NOW - 86400000, NOW - 1000,
                   "hard", "complete", f"rg_{hphash}", None))

    # ---- Operations log with error patterns ----
    ops = ["get", "get", "get", "put_start", "put_end", "evict"]
    node_cycle = ["p0", "p1", "p2", "p3", "d0", "d1"]
    for i in range(600):
        ts = NOW - 3600000 + i * 6000
        op = ops[i % 6]
        node = node_cycle[i % 6]
        status = "success"
        error = None
        latency = 1.0 + (i * 17) % 50

        if node in ("p0", "p1") and op == "put_start" and i % 4 == 0:
            status = "error"
            error = "CAPACITY_EXCEEDED"
            latency = 0.5
        if node in ("p0", "p1") and op == "put_start" and i % 12 == 0:
            status = "error"
            error = "ZOMBIE_OBJECT_BLOCKING"
            latency = 0.3

        c.execute("""INSERT INTO operations_log
                     (timestamp,operation,block_id,node_id,status,error_msg,latency_ms)
                     VALUES (?,?,?,?,?,?,?)""",
                  (ts, op, f"blk_{i % block_id:05d}", node, status, error, latency))

    conn.commit()

    # Print stats
    print("=== Node Utilization ===")
    for nid, _, cap in NODES:
        cnt = c.execute("SELECT COUNT(*) FROM blocks WHERE node_id=?",
                        (nid,)).fetchone()[0]
        print(f"  {nid}: {cnt}/{cap} ({100*cnt/cap:.1f}%)")

    zc = c.execute(
        "SELECT COUNT(*) FROM blocks WHERE status='init' AND put_start_time<?",
        (NOW - ZOMBIE_TIMEOUT,)).fetchone()[0]
    print(f"Zombie blocks: {zc}")

    epc = c.execute(
        "SELECT COUNT(*) FROM blocks WHERE pin_type='soft' AND last_accessed<?",
        (NOW - SOFT_PIN_TTL,)).fetchone()[0]
    print(f"Expired soft pins: {epc}")

    oc = c.execute("""
        SELECT pc.hash_id FROM prefix_chains pc
        WHERE pc.parent_hash_id IS NOT NULL
          AND pc.parent_hash_id NOT IN (SELECT hash_id FROM prefix_chains)
    """).fetchall()
    print(f"Orphaned chains: {len(oc)}")

    conn.close()

    # ---- Generate upcoming request trace ----
    requests = []
    for r in range(200):
        if r < 120:
            s = r % 10
        elif r < 180:
            s = 10 + (r % 10)
        else:
            s = 20 + (r % 10)

        chain = sessions[s]
        chain_len = len(chain)
        prefix_len = 3 + (r * 7) % max(1, chain_len - 3)
        prefix_len = min(prefix_len, chain_len)
        hash_ids = list(chain[:prefix_len])

        num_uncached = 1 + r % 3
        for j in range(num_uncached):
            hash_ids.append(90000 + r * 10 + j)

        requests.append({
            "request_id": f"req_{r:03d}",
            "timestamp_ms": r * 300,
            "input_length": len(hash_ids) * BLOCK_SIZE + r % BLOCK_SIZE,
            "output_length": 50 + (r * 13) % 450,
            "hash_ids": hash_ids,
        })

    with open(TRACE_PATH, "w") as f:
        json.dump(requests, f, indent=2)
    print(f"Generated {len(requests)} requests")

    # ---- Write config ----
    config = {
        "cluster": {nid: {"type": ntype, "capacity_blocks": cap}
                    for nid, ntype, cap in NODES},
        "block_size_tokens": BLOCK_SIZE,
        "soft_pin_ttl_ms": SOFT_PIN_TTL,
        "zombie_timeout_ms": ZOMBIE_TIMEOUT,
        "current_time_ms": NOW,
        "eviction_high_watermark": 0.95,
        "max_replicas_per_block": 3,
        "target_cache_hit_rate": 0.45,
        "target_max_node_utilization": 0.90,
    }
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print("Config written")


if __name__ == "__main__":
    main()
