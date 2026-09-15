#!/usr/bin/env python3

"""DDoS traffic detection solution.
Extracts TCP flags from pcap via tshark, correlates with SQLite flow records,
and applies three detection algorithms."""

import json
import os
import sqlite3
import subprocess
from collections import defaultdict


def extract_tcp_flags_from_pcap():
    """Use tshark to extract per-packet TCP flags and group by 5-tuple."""
    result = subprocess.run([
        'tshark', '-r', '/app/captures/traffic.pcap',
        '-Y', 'tcp',
        '-T', 'fields',
        '-e', 'ip.src', '-e', 'ip.dst',
        '-e', 'tcp.srcport', '-e', 'tcp.dstport',
        '-e', 'tcp.flags',
        '-e', 'tcp.window_size_value',
        '-E', 'separator=|', '-E', 'header=n'
    ], capture_output=True, text=True, timeout=300)

    flow_info = {}
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        parts = line.split('|')
        if len(parts) < 6:
            continue
        src, dst, sport, dport, flags_hex, window = parts[:6]
        try:
            key = (src, dst, int(sport), int(dport))
        except (ValueError, TypeError):
            continue

        if key not in flow_info:
            flow_info[key] = {'flag_vals': set(), 'windows': []}

        try:
            flow_info[key]['flag_vals'].add(int(flags_hex, 16))
        except (ValueError, TypeError):
            pass
        try:
            flow_info[key]['windows'].append(int(window))
        except (ValueError, TypeError):
            pass

    return flow_info


def load_flows():
    db = sqlite3.connect("/app/network.db")
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute("SELECT id, ts, src, dst, sport, dport, proto, pkts, bytes, dur_ms FROM netflow")
    flows = [dict(row) for row in cur.fetchall()]
    db.close()
    return flows


def is_syn_only(flag_vals):
    """True if all observed TCP flags for this flow are pure SYN (0x02)."""
    if not flag_vals:
        return False
    return all(f == 0x02 for f in flag_vals)


def detect_syn_flood(flows, pcap_info):
    """Detect pulsing SYN flood: temporal clustering of SYN-only flows."""
    WINDOW_SEC = 30
    COUNT_THRESHOLD = 15
    DIVERSITY_RATIO = 0.3

    min_ts = min(f["ts"] for f in flows)

    syn_only_flows = []
    for f in flows:
        if f["proto"] != "TCP":
            continue
        key = (f["src"], f["dst"], f["sport"], f["dport"])
        info = pcap_info.get(key, {})
        if is_syn_only(info.get('flag_vals', set())):
            syn_only_flows.append(f)

    windows = defaultdict(lambda: defaultdict(list))
    for f in syn_only_flows:
        w = int((f["ts"] - min_ts) / WINDOW_SEC)
        windows[w][f["dst"]].append(f)

    attack_ids = set()
    for w, dst_map in windows.items():
        for dst, flist in dst_map.items():
            if len(flist) >= COUNT_THRESHOLD:
                unique_srcs = len(set(f["src"] for f in flist))
                if unique_srcs >= len(flist) * DIVERSITY_RATIO:
                    for f in flist:
                        attack_ids.add(f["id"])

    return sorted(attack_ids)


def detect_slowloris(flows, pcap_info):
    """Detect Slowloris: long-lived TCP connections with minimal data on HTTP ports."""
    DUR_THRESHOLD = 25000
    PKTS_THRESHOLD = 20
    BYTES_THRESHOLD = 2000
    HTTP_PORTS = {80, 8080}

    attack_ids = []
    for f in flows:
        if (f["proto"] == "TCP"
                and f["dport"] in HTTP_PORTS
                and f["dur_ms"] >= DUR_THRESHOLD
                and f["pkts"] <= PKTS_THRESHOLD
                and f["bytes"] <= BYTES_THRESHOLD):
            attack_ids.append(f["id"])

    return sorted(attack_ids)


def detect_dns_amplification(flows, pcap_info):
    """Detect DNS amplification: large UDP from port 53 concentrated on targets."""
    BYTES_THRESHOLD = 1400
    DST_COUNT_THRESHOLD = 20

    candidates = [
        f for f in flows
        if f["proto"] == "UDP" and f["sport"] == 53 and f["bytes"] >= BYTES_THRESHOLD
    ]
    if not candidates:
        return []

    dst_counts = defaultdict(int)
    for f in candidates:
        dst_counts[f["dst"]] += 1

    amp_targets = {dst for dst, cnt in dst_counts.items() if cnt >= DST_COUNT_THRESHOLD}
    attack_ids = [f["id"] for f in candidates if f["dst"] in amp_targets]
    return sorted(attack_ids)


def main():
    print("Extracting TCP flags from pcap using tshark...")
    pcap_info = extract_tcp_flags_from_pcap()
    print(f"  Extracted info for {len(pcap_info)} TCP flows from pcap")

    print("Loading flows from SQLite...")
    flows = load_flows()
    print(f"  Loaded {len(flows)} flows")

    os.makedirs("/app/output", exist_ok=True)

    results = {
        "syn_flood": detect_syn_flood(flows, pcap_info),
        "slowloris": detect_slowloris(flows, pcap_info),
        "dns_amp": detect_dns_amplification(flows, pcap_info),
    }

    for attack_type, ids in results.items():
        with open(f"/app/output/{attack_type}.json", "w") as f:
            json.dump({"flow_ids": ids}, f, indent=2)
        print(f"{attack_type}: {len(ids)} flows classified")

    print(f"Total flagged: {sum(len(v) for v in results.values())}")


if __name__ == "__main__":
    main()
