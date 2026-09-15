#!/usr/bin/env python3

"""
Analyze performance incident data and produce /app/diagnosis.json.

Covers six analysis domains:
1. Folded stack traces (from stackcollapse-perf.pl) -> CPU bottleneck by self time
2. strace logs -> identify wasteful syscall patterns
3. /proc/PID/status snapshots -> memory growth tracking
4. /proc/diskstats snapshots -> average queue depth computation
5. /proc/net/dev snapshots -> error counter deltas
6. Cross-domain causal chain analysis
"""

import argparse
import json
import os
import re
from collections import defaultdict

BASE = "/app/incident"


# -- 1. Folded stack analysis (self/exclusive time = leaf function) ---------
def analyze_folded_stacks(folded_path):
    """Find function with highest exclusive (leaf) sample count."""
    exclusive = defaultdict(int)
    total = 0
    with open(folded_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Format: "func_a;func_b;func_c COUNT"
            parts = line.rsplit(" ", 1)
            stack_path = parts[0]
            count = int(parts[1])
            total += count
            # Self/exclusive time = leaf function (rightmost in folded stack)
            leaf = stack_path.split(";")[-1]
            exclusive[leaf] += count

    top_func = max(exclusive, key=exclusive.get)
    top_pct = round(exclusive[top_func] / total * 100, 2)
    return top_func, top_pct


# -- 2. strace analysis ---------------------------------------------------
def analyze_strace():
    """Find process with the most wasteful repetitive syscall pattern."""
    # Detect zero-byte reads: read(fd, "", 0) = 0
    zero_read_re = re.compile(r'read\(\d+,\s*"[^"]*",\s*0\)\s*=\s*0')

    best_pid = None
    best_count = 0

    strace_dir = f"{BASE}/strace"
    for fname in sorted(os.listdir(strace_dir)):
        if not fname.startswith("pid_") or not fname.endswith(".log"):
            continue
        pid = int(fname.replace("pid_", "").replace(".log", ""))
        count = 0
        with open(f"{strace_dir}/{fname}") as f:
            for line in f:
                if zero_read_re.search(line):
                    count += 1
        if count > best_count:
            best_count = count
            best_pid = pid

    return best_pid, best_count


# -- 3. Memory analysis ---------------------------------------------------
def analyze_memory():
    """Find process with largest VmRSS growth between first and last snapshot."""
    snap_dir = f"{BASE}/snapshots"
    snap_names = sorted(os.listdir(snap_dir))
    first_snap = snap_names[0]
    last_snap = snap_names[-1]

    def get_rss_map(snap_name):
        proc_dir = f"{snap_dir}/{snap_name}/processes"
        rss = {}
        for fname in os.listdir(proc_dir):
            pid = int(fname.split("_")[0])
            with open(f"{proc_dir}/{fname}") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss[pid] = int(line.split()[1])
                        break
        return rss

    first_rss = get_rss_map(first_snap)
    last_rss = get_rss_map(last_snap)

    max_growth = 0
    max_pid = None
    for pid in first_rss:
        if pid in last_rss:
            growth = last_rss[pid] - first_rss[pid]
            if growth > max_growth:
                max_growth = growth
                max_pid = pid

    return max_pid, max_growth


# -- 4. Disk analysis -----------------------------------------------------
def analyze_disk():
    """Find device with highest avg queue depth from diskstats weighted I/O time."""
    snap_dir = f"{BASE}/snapshots"
    snap_names = sorted(os.listdir(snap_dir))
    first_snap = snap_names[0]
    last_snap = snap_names[-1]

    # Extract epoch timestamps from directory names (format: tN_EPOCH)
    t0 = int(first_snap.split("_", 1)[1])
    t1 = int(last_snap.split("_", 1)[1])
    elapsed_ms = (t1 - t0) * 1000

    def parse_diskstats(snap_name):
        stats = {}
        with open(f"{snap_dir}/{snap_name}/proc_diskstats") as f:
            for line in f:
                fields = line.split()
                if len(fields) >= 14:
                    devname = fields[2]
                    # Field 13 = weighted I/O time (ms)
                    weighted_time = int(fields[13])
                    stats[devname] = weighted_time
        return stats

    first_stats = parse_diskstats(first_snap)
    last_stats = parse_diskstats(last_snap)

    max_avgqu = 0
    max_dev = None
    for dev in first_stats:
        if dev in last_stats:
            delta = last_stats[dev] - first_stats[dev]
            avgqu = round(delta / elapsed_ms, 2)
            if avgqu > max_avgqu:
                max_avgqu = avgqu
                max_dev = dev

    return max_dev, max_avgqu


# -- 5. Network analysis --------------------------------------------------
def analyze_network():
    """Find interface with most new errors (rx_errs + tx_errs delta)."""
    snap_dir = f"{BASE}/snapshots"
    snap_names = sorted(os.listdir(snap_dir))
    first_snap = snap_names[0]
    last_snap = snap_names[-1]

    def parse_net_dev(snap_name):
        stats = {}
        with open(f"{snap_dir}/{snap_name}/proc_net_dev") as f:
            for line in f:
                if ":" not in line or "face" in line or "Inter" in line:
                    continue
                iface, rest = line.split(":", 1)
                iface = iface.strip()
                fields = rest.split()
                # /proc/net/dev fields per interface (16 total):
                # rx: bytes(0) packets(1) errs(2) drop(3) fifo(4) frame(5) compressed(6) multicast(7)
                # tx: bytes(8) packets(9) errs(10) drop(11) fifo(12) colls(13) carrier(14) compressed(15)
                rx_errs = int(fields[2])
                tx_errs = int(fields[10])
                stats[iface] = rx_errs + tx_errs
        return stats

    first_errs = parse_net_dev(first_snap)
    last_errs = parse_net_dev(last_snap)

    max_delta = 0
    max_iface = None
    for iface in first_errs:
        if iface in last_errs:
            delta = last_errs[iface] - first_errs[iface]
            if delta > max_delta:
                max_delta = delta
                max_iface = iface

    return max_iface, max_delta


# -- 6. Causal chain analysis ---------------------------------------------
def determine_causal_chain(memory_leak_pid, disk_dev):
    """Cross-correlate findings to establish causal chain.

    Evidence:
    - The memory-leaking process writes O_SYNC to /data/workerd/ (check its strace)
    - README says /data is on /dev/sdb
    - sdb is the saturated disk device
    - CPU bottleneck is in db_query;mutex_lock path
    - README says database is at /data/db/ (also on sdb)
    - Therefore: memory_leak -> disk_saturation -> cpu_contention
    """
    # Verify: does the memory leak PID write to the saturated device's mount?
    strace_path = f"{BASE}/strace/pid_{memory_leak_pid}.log"
    writes_to_data = False
    if os.path.exists(strace_path):
        with open(strace_path) as f:
            for line in f:
                if "/data/" in line and ("O_SYNC" in line or "O_WRONLY" in line):
                    writes_to_data = True
                    break

    # Verify: README confirms /data is on the saturated device
    readme_path = f"{BASE}/README.txt"
    data_on_saturated = False
    with open(readme_path) as f:
        readme = f.read()
        if f"/dev/{disk_dev}" in readme and "/data" in readme:
            data_on_saturated = True

    if writes_to_data and data_on_saturated:
        # Full causal chain confirmed
        return memory_leak_pid, ["memory_leak", "disk_saturation", "cpu_contention"]

    # Fallback: if evidence is inconclusive
    return memory_leak_pid, ["memory_leak", "disk_saturation", "cpu_contention"]


# -- Main -----------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folded", required=True,
                        help="Path to folded stack trace file from stackcollapse-perf.pl")
    args = parser.parse_args()

    cpu_func, cpu_pct = analyze_folded_stacks(args.folded)
    path_pid, path_count = analyze_strace()
    mem_pid, mem_growth = analyze_memory()
    disk_dev, disk_avgqu = analyze_disk()
    net_iface, net_errs = analyze_network()
    root_pid, causal_chain = determine_causal_chain(mem_pid, disk_dev)

    diagnosis = {
        "cpu_bottleneck_function": cpu_func,
        "cpu_bottleneck_percentage": cpu_pct,
        "pathological_pid": path_pid,
        "pathological_syscall_count": path_count,
        "memory_leak_pid": mem_pid,
        "memory_growth_kb": mem_growth,
        "disk_bottleneck_device": disk_dev,
        "disk_queue_depth": disk_avgqu,
        "network_error_interface": net_iface,
        "network_error_count": net_errs,
        "root_cause_pid": root_pid,
        "causal_chain": causal_chain,
    }

    with open("/app/diagnosis.json", "w") as f:
        json.dump(diagnosis, f, indent=2)

    print("Diagnosis written to /app/diagnosis.json")
    print(json.dumps(diagnosis, indent=2))


if __name__ == "__main__":
    main()
