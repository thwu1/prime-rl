#!/usr/bin/env python3
"""

Redis cluster recovery solution.
Starts a pre-configured 3-node cluster from persisted state, detects slot
distribution imbalance, performs manual slot migration to achieve an even
distribution, verifies data integrity, and writes a health report.
"""

import csv
import json
import os
import subprocess
import sys
import time

import redis

HASH_SLOT_COUNT = 16384
PORTS = [7000, 7001, 7002]
CONF_DIR = "/app/conf"
DATASET_PATH = "/app/dataset.csv"
REPORT_PATH = "/app/cluster_report.json"


def crc16(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def key_slot(key):
    k = key
    s = k.find("{")
    if s != -1:
        e = k.find("}", s + 1)
        if e != -1 and e != s + 1:
            k = k[s + 1:e]
    return crc16(k.encode()) % HASH_SLOT_COUNT


def get_conn(port):
    return redis.Redis(host="127.0.0.1", port=port, decode_responses=True,
                       socket_timeout=10)


def wait_for_server(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = redis.Redis(host="127.0.0.1", port=port, socket_timeout=2,
                            decode_responses=True)
            if r.ping():
                r.close()
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def get_node_ids(conn):
    raw = conn.execute_command("CLUSTER", "NODES")
    result = {}
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        addr = parts[1].split("@")[0].split(",")[0]
        port = int(addr.split(":")[1])
        result[port] = parts[0]
    return result


def get_slot_ownership(conn):
    """Parse CLUSTER NODES -> {port: set_of_owned_slots}."""
    raw = conn.execute_command("CLUSTER", "NODES")
    result = {}
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        addr = parts[1].split("@")[0].split(",")[0]
        port = int(addr.split(":")[1])
        owned = set()
        for token in parts[8:]:
            if token.startswith("["):
                continue
            if "-" in token:
                lo, hi = token.split("-")
                try:
                    owned.update(range(int(lo), int(hi) + 1))
                except ValueError:
                    pass
            else:
                try:
                    owned.add(int(token))
                except ValueError:
                    pass
        result[port] = owned
    return result


def calculate_target(ports):
    """Even distribution: each node gets ~16384/n contiguous slots."""
    n = len(ports)
    slots_per = HASH_SLOT_COUNT // n
    remainder = HASH_SLOT_COUNT % n
    target = {}
    start = 0
    for i, port in enumerate(sorted(ports)):
        count = slots_per + (1 if i < remainder else 0)
        target[port] = set(range(start, start + count))
        start += count
    return target


def migrate_slots(conns, source_port, target_port, slots, node_ids):
    """Migrate slots from source to target using manual per-slot protocol."""
    source = conns[source_port]
    target = conns[target_port]
    source_id = node_ids[source_port]
    target_id = node_ids[target_port]
    all_ports = list(conns.keys())

    total_keys = 0
    for slot in sorted(slots):
        target.execute_command("CLUSTER", "SETSLOT", slot, "IMPORTING", source_id)
        source.execute_command("CLUSTER", "SETSLOT", slot, "MIGRATING", target_id)

        while True:
            keys = source.execute_command("CLUSTER", "GETKEYSINSLOT", slot, 100)
            if not keys:
                break
            if isinstance(keys, str):
                keys = [keys]
            source.execute_command(
                "MIGRATE", "127.0.0.1", target_port,
                "", 0, 5000, "REPLACE", "KEYS", *keys,
            )
            total_keys += len(keys)

        for p in all_ports:
            conns[p].execute_command("CLUSTER", "SETSLOT", slot, "NODE", target_id)

    return total_keys


def main():
    print("=== Redis Cluster Recovery ===")

    # 1. Start nodes from persisted state
    print("[1] Starting Redis nodes from persisted state ...")
    for port in PORTS:
        conf = os.path.join(CONF_DIR, f"node-{port}.conf")
        subprocess.run(["redis-server", conf, "--daemonize", "yes"], check=True)

    for port in PORTS:
        if not wait_for_server(port):
            print(f"FATAL: Node {port} failed to start")
            sys.exit(1)
        print(f"  :{port} ready")

    # 2. Wait for cluster convergence
    print("[2] Waiting for cluster convergence ...")
    conns = {p: get_conn(p) for p in PORTS}
    for attempt in range(60):
        all_ok = all(
            "cluster_state:ok" in conns[p].execute_command("CLUSTER", "INFO")
            for p in PORTS
        )
        if all_ok:
            break
        time.sleep(1)

    # 3. Diagnose current slot distribution
    print("[3] Analyzing slot distribution ...")
    current = get_slot_ownership(conns[7000])
    for p in sorted(current):
        print(f"  :{p} owns {len(current[p])} slots")

    target = calculate_target(PORTS)
    for p in sorted(target):
        print(f"  Target :{p} -> {len(target[p])} slots")

    # 4. Compute migration plan
    migrations = {}
    for tgt_port, tgt_slots in target.items():
        for slot in tgt_slots:
            for cur_port, cur_slots in current.items():
                if slot in cur_slots:
                    if cur_port != tgt_port:
                        key = (cur_port, tgt_port)
                        migrations.setdefault(key, set()).add(slot)
                    break

    node_ids = get_node_ids(conns[7000])

    # 5. Execute migrations
    print(f"[4] Executing {len(migrations)} migration group(s) ...")
    total_migrated = 0
    for (src, tgt), slots in sorted(migrations.items()):
        print(f"  {len(slots)} slots: :{src} -> :{tgt}")
        keys_moved = migrate_slots(conns, src, tgt, slots, node_ids)
        total_migrated += keys_moved
        print(f"  Moved {keys_moved} keys")

    time.sleep(3)

    # 6. Verify data integrity
    print("[5] Verifying data integrity ...")
    final = get_slot_ownership(conns[7000])
    s2p = {}
    for port, slots in final.items():
        for slot in slots:
            s2p[slot] = port

    verified = True
    with open(DATASET_PATH) as f:
        for row in csv.DictReader(f):
            slot = key_slot(row["key"])
            port = s2p.get(slot)
            if port is None:
                print(f"  ERROR: no owner for slot {slot} (key={row['key']})")
                verified = False
                continue
            val = conns[port].get(row["key"])
            if val != row["value"]:
                print(f"  MISMATCH: {row['key']} expected={row['value']!r} got={val!r}")
                verified = False

    print(f"  Verification: {'PASS' if verified else 'FAIL'}")

    # 7. Build report
    print("[6] Writing cluster report ...")
    raw = conns[7000].execute_command("CLUSTER", "NODES")
    nodes = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        node_id = parts[0]
        addr = parts[1].split("@")[0].split(",")[0]
        port = int(addr.split(":")[1])
        flags = parts[2]
        role = "master" if "master" in flags else "slave"
        slot_tokens = [t for t in parts[8:] if not t.startswith("[")]
        nodes.append({
            "port": port,
            "node_id": node_id,
            "role": role,
            "slots": " ".join(slot_tokens),
        })

    report = {
        "nodes": sorted(nodes, key=lambda n: n["port"]),
        "migrated_key_count": total_migrated,
        "all_keys_verified": verified,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"  Migrated {total_migrated} keys total")
    print(f"  Report written to {REPORT_PATH}")
    print("=== Recovery complete ===")


if __name__ == "__main__":
    main()
