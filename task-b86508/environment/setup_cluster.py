#!/usr/bin/env python3
"""Build-time script: initialize Redis cluster with imbalanced slot distribution."""
import csv
import os
import subprocess
import sys
import time

HASH_SLOT_COUNT = 16384


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


NODES = [
    {"port": 7000, "dir": "/app/data/node0", "slot_start": 0, "slot_end": 10922},
    {"port": 7001, "dir": "/app/data/node1", "slot_start": 10923, "slot_end": 13652},
    {"port": 7002, "dir": "/app/data/node2", "slot_start": 13653, "slot_end": 16383},
]


def cli(port, *args):
    result = subprocess.run(
        ["redis-cli", "-p", str(port)] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout.strip()


def owner_port(slot):
    for n in NODES:
        if n["slot_start"] <= slot <= n["slot_end"]:
            return n["port"]
    raise ValueError(f"Slot {slot} has no owner")


def main():
    for n in NODES:
        os.makedirs(n["dir"], exist_ok=True)

    for n in NODES:
        subprocess.run(
            ["redis-server", f"/app/conf/node-{n['port']}.conf", "--daemonize", "yes"],
            check=True,
        )

    time.sleep(3)

    for n in NODES:
        for attempt in range(20):
            if cli(n["port"], "PING") == "PONG":
                break
            time.sleep(1)
        else:
            sys.exit(f"Node {n['port']} failed to start")

    for i, n in enumerate(NODES):
        cli(n["port"], "CLUSTER", "SET-CONFIG-EPOCH", str(i + 1))

    for n in NODES:
        cli(n["port"], "CLUSTER", "ADDSLOTSRANGE", str(n["slot_start"]), str(n["slot_end"]))

    for n in NODES[1:]:
        cli(NODES[0]["port"], "CLUSTER", "MEET", "127.0.0.1", str(n["port"]))

    for _ in range(30):
        info = cli(NODES[0]["port"], "CLUSTER", "INFO")
        if "cluster_state:ok" in info:
            break
        time.sleep(1)

    loaded = 0
    with open("/app/dataset.csv") as f:
        for row in csv.DictReader(f):
            slot = key_slot(row["key"])
            port = owner_port(slot)
            cli(port, "SET", row["key"], row["value"])
            loaded += 1
    print(f"Loaded {loaded} keys")

    for n in NODES:
        subprocess.run(
            ["redis-cli", "-p", str(n["port"]), "SHUTDOWN", "SAVE"],
            capture_output=True, timeout=60,
        )

    time.sleep(2)
    print("Build-time cluster setup complete.")


if __name__ == "__main__":
    main()
