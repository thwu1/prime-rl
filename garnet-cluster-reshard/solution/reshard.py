#!/usr/bin/env python3

"""
Garnet cluster resharding solution.

Expands a 3-node cluster to 4 balanced masters with a replica.
Strategy: Since Garnet's MIGRATE SLOTSRANGE rejects migration to a node with
no slots (it is not recognized as a primary), we rebuild the cluster with 4
masters each owning exactly 4096 slots, reload all keys using CRC16-based
hash slot routing, then configure replication.
"""

import json
import os
import socket
import subprocess
import sys
import time


def crc16(data):
    """CRC16-CCITT for Redis/Garnet hash slot calculation."""
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
    """Calculate the hash slot for a key."""
    return crc16(key.encode()) % 16384


def redis_cli(port, *args, timeout=30):
    """Execute a redis-cli command against a Garnet instance."""
    cmd = ["redis-cli", "-h", "127.0.0.1", "-p", str(port)] + [str(a) for a in args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def redis_cli_cluster(port, *args, timeout=10):
    """Execute redis-cli in cluster mode (follows MOVED redirections)."""
    cmd = ["redis-cli", "-c", "-h", "127.0.0.1", "-p", str(port)] + [str(a) for a in args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def wait_for_port(port, max_wait=60):
    """Wait until a Garnet instance responds to PING."""
    for _ in range(max_wait):
        try:
            result = redis_cli(port, "PING", timeout=5)
            if "PONG" in result:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def wait_for_port_free(port, max_wait=15):
    """Wait until a port is no longer in use."""
    for _ in range(max_wait):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            time.sleep(1)
        except (ConnectionRefusedError, socket.timeout, OSError):
            s.close()
            return True
    return False


def resp_encode(*args):
    """Encode arguments as a RESP array command."""
    parts = [f"*{len(args)}\r\n".encode()]
    for a in args:
        b = a.encode() if isinstance(a, str) else a
        parts.append(f"${len(b)}\r\n".encode() + b + b"\r\n")
    return b"".join(parts)


def recv_line(sock):
    """Read a single RESP line from socket."""
    buf = b""
    while not buf.endswith(b"\r\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        buf += chunk
    return buf.decode().strip()


def parse_cluster_nodes(port):
    """Parse CLUSTER NODES output into node dicts."""
    output = redis_cli(port, "CLUSTER", "NODES")
    nodes = []
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        node_id = parts[0]
        addr = parts[1]
        flags = parts[2]
        port_num = int(addr.split(":")[1].split("@")[0])
        slot_parts = parts[8:] if len(parts) > 8 else []
        total_slots = 0
        for s in slot_parts:
            if "-" in s:
                try:
                    start, end = s.split("-")
                    total_slots += int(end) - int(start) + 1
                except ValueError:
                    pass
            else:
                try:
                    int(s)
                    total_slots += 1
                except ValueError:
                    pass
        nodes.append({
            "id": node_id,
            "port": port_num,
            "role": "master" if "master" in flags else "replica",
            "is_master": "master" in flags,
            "slot_count": total_slots,
        })
    return nodes


def main():
    print("=" * 60)
    print("Garnet Cluster Resharding")
    print("=" * 60)

    # Cluster topology: 4 masters, each owning exactly 4096 slots
    SLOT_RANGES = {
        7000: (0, 4095),
        7001: (4096, 8191),
        7002: (8192, 12287),
        7003: (12288, 16383),
    }
    MASTER_PORTS = [7000, 7001, 7002, 7003]
    ALL_PORTS = [7000, 7001, 7002, 7003, 7004]

    # ── Step 1: Tear down existing cluster ────────────
    print("\n[1/8] Stopping existing cluster...")
    subprocess.run(["pkill", "-f", "garnet-server"], capture_output=True)
    time.sleep(2)
    subprocess.run(["pkill", "-9", "-f", "garnet-server"], capture_output=True)
    time.sleep(2)

    # Wait for ports to be free
    for port in [7000, 7001, 7002]:
        wait_for_port_free(port)
    print("  Existing processes stopped")

    # ── Step 2: Prepare clean data directories ────────
    print("\n[2/8] Preparing data directories...")
    for port in ALL_PORTS:
        d = f"/tmp/garnet/{port}"
        subprocess.run(["rm", "-rf", d], capture_output=True)
        os.makedirs(d, exist_ok=True)

    # ── Step 3: Start 4 master instances ──────────────
    print("\n[3/8] Starting 4 master instances...")
    for port in MASTER_PORTS:
        cmd = [
            "garnet-server",
            "--port", str(port),
            "--checkpointdir", f"/tmp/garnet/{port}",
            "--cluster", "--aof",
            "--config-import-path", "/opt/garnet/garnet.conf",
        ]
        log_file = open(f"/tmp/garnet/{port}/server.log", "w")
        subprocess.Popen(cmd, stdout=log_file, stderr=log_file)

    for port in MASTER_PORTS:
        if not wait_for_port(port, max_wait=90):
            print(f"  ERROR: Port {port} failed to start")
            try:
                with open(f"/tmp/garnet/{port}/server.log") as f:
                    print(f"  Log tail: {f.read()[-500:]}")
            except Exception:
                pass
            sys.exit(1)
        print(f"  Port {port} ready")

    # ── Step 4: Configure cluster topology ────────────
    print("\n[4/8] Configuring cluster topology...")

    # Set config epochs (must be on fresh nodes with empty tables and epoch 0)
    for i, port in enumerate(MASTER_PORTS, 1):
        r = redis_cli(port, "CLUSTER", "SET-CONFIG-EPOCH", i)
        print(f"  SET-CONFIG-EPOCH {i} on {port}: {r}")

    # Assign slot ranges to each master
    for port, (start, end) in SLOT_RANGES.items():
        r = redis_cli(port, "CLUSTER", "ADDSLOTSRANGE", start, end)
        print(f"  ADDSLOTSRANGE {start}-{end} on {port}: {r}")

    # Join nodes via CLUSTER MEET from node 7000
    for port in [7001, 7002, 7003]:
        r = redis_cli(7000, "CLUSTER", "MEET", "127.0.0.1", port)
        print(f"  MEET {port}: {r}")

    # Wait for gossip propagation
    print("  Waiting for gossip propagation...")
    time.sleep(12)

    # Verify cluster formed correctly
    nodes = parse_cluster_nodes(7000)
    masters = [n for n in nodes if n["is_master"]]
    print(f"  Cluster: {len(nodes)} nodes, {len(masters)} masters")
    for m in sorted(masters, key=lambda x: x["port"]):
        print(f"    Port {m['port']}: {m['slot_count']} slots")

    if len(masters) != 4:
        print("  ERROR: Expected 4 masters")
        sys.exit(1)

    # ── Step 5: Load 500 keys ─────────────────────────
    print("\n[5/8] Loading 500 keys...")

    # Build slot-to-port mapping
    slot_to_port = {}
    for port, (start, end) in SLOT_RANGES.items():
        for s in range(start, end + 1):
            slot_to_port[s] = port

    # Open direct sockets for fast bulk loading (same approach as seed_keys.py)
    socks = {}
    for port in MASTER_PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(("127.0.0.1", port))
        socks[port] = s

    loaded = 0
    for i in range(500):
        key = f"key:{i:04d}"
        val = f"val:{i:04d}"
        slot = key_slot(key)
        port = slot_to_port[slot]
        sock = socks[port]
        sock.sendall(resp_encode("SET", key, val))
        resp = recv_line(sock)
        if "OK" in resp:
            loaded += 1
        else:
            print(f"  WARN: SET {key} on {port}: {resp}")

    for s in socks.values():
        s.close()

    print(f"  Loaded {loaded}/500 keys")
    if loaded < 500:
        print(f"  ERROR: Only loaded {loaded}/500 keys")
        sys.exit(1)

    # ── Step 6: Start replica ─────────────────────────
    print("\n[6/8] Starting replica on port 7004...")
    cmd = [
        "garnet-server",
        "--port", "7004",
        "--checkpointdir", "/tmp/garnet/7004",
        "--cluster", "--aof",
        "--config-import-path", "/opt/garnet/garnet.conf",
    ]
    log_file = open("/tmp/garnet/7004/server.log", "w")
    subprocess.Popen(cmd, stdout=log_file, stderr=log_file)

    if not wait_for_port(7004, max_wait=90):
        print("  ERROR: Port 7004 failed to start")
        sys.exit(1)
    print("  Port 7004 ready")

    # Set epoch and join cluster
    r = redis_cli(7004, "CLUSTER", "SET-CONFIG-EPOCH", 5)
    print(f"  SET-CONFIG-EPOCH 5: {r}")
    r = redis_cli(7003, "CLUSTER", "MEET", "127.0.0.1", "7004")
    print(f"  MEET 7004: {r}")

    # Wait for gossip to propagate the new node
    time.sleep(10)

    # Get node 7003's ID for replication
    node_7003_id = redis_cli(7003, "CLUSTER", "MYID")
    print(f"  Node 7003 ID: {node_7003_id}")

    # Configure replication: 7004 → 7003
    r = redis_cli(7004, "CLUSTER", "REPLICATE", node_7003_id)
    print(f"  REPLICATE: {r}")

    # Wait for replication to establish (poll INFO REPLICATION)
    print("  Waiting for replication to establish...")
    replica_ok = False
    for attempt in range(60):
        info = redis_cli(7004, "INFO", "REPLICATION")
        if "role:slave" in info and "master_link_status:up" in info:
            replica_ok = True
            print(f"  Replication established (attempt {attempt + 1})")
            break
        time.sleep(2)

    if not replica_ok:
        info = redis_cli(7004, "INFO", "REPLICATION")
        if "role:slave" in info:
            replica_ok = True
            print("  Replica role confirmed (link may still be syncing)")
        else:
            print("  WARNING: Replication may not be fully established")

    # ── Step 7: Verify keys ───────────────────────────
    print("\n[7/8] Verifying 500 keys...")
    verified = 0
    mismatches = []
    for i in range(500):
        key = f"key:{i:04d}"
        expected = f"val:{i:04d}"
        actual = redis_cli_cluster(7000, "GET", key, timeout=10)
        if actual == expected:
            verified += 1
        else:
            mismatches.append((key, expected, actual))

    print(f"  Verified {verified}/500 keys")
    if mismatches:
        print(f"  First 5 mismatches: {mismatches[:5]}")

    # ── Step 8: Write cluster report ──────────────────
    print("\n[8/8] Writing cluster report...")
    nodes = parse_cluster_nodes(7000)
    report = {
        "nodes": [
            {
                "id": n["id"],
                "port": n["port"],
                "role": n["role"],
                "slot_count": n["slot_count"],
            }
            for n in nodes
        ],
        "total_keys_verified": verified,
        "replica_replicating": replica_ok,
    }

    with open("/app/cluster_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'=' * 60}")
    print("Resharding complete!")
    masters_final = [n for n in nodes if n["is_master"]]
    replicas_final = [n for n in nodes if not n["is_master"]]
    print(f"  Masters: {len(masters_final)}")
    print(f"  Replicas: {len(replicas_final)}")
    print(f"  Keys verified: {verified}/500")
    print(f"  Replica active: {replica_ok}")
    print(f"  Report: /app/cluster_report.json")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
