#!/usr/bin/env python3
"""
Generate diagnostic data for the HTB QoS forensics task.
Produces raw tc command output format, filter dumps, flow logs,
SLA targets, and intended hierarchy specification.

"""
import json
import os
import csv

CAPTURE_DIR = "/app/captures"
INTERVAL = 5  # seconds between snapshots
NUM_SNAPSHOTS = 20
PKT_SIZE = 1000  # average packet size in bytes


def parse_rate(rate_str):
    if rate_str.endswith("Mbit"):
        return int(rate_str[:-4]) * 1_000_000
    elif rate_str.endswith("Kbit"):
        return int(rate_str[:-4]) * 1_000
    return int(rate_str)


# ---- ACTUAL (misconfigured) class properties ----
# BUG 1: 1:201 ceil should be 40Mbit but is set to 15Mbit (same as rate)
# BUG 2: 1:301 quantum should be 1500 but is set to 60000
# BUG 3: VoIP u32 filter matches DSCP 44 (0xB0) instead of DSCP 46/EF (0xB8)

LEAF_CLASSES = {
    "1:100": {"parent": "1:10", "rate": "20Mbit", "ceil": "40Mbit",
              "burst": "2500b", "cburst": "5000b", "prio": 1,
              "quantum": 1500, "leaf_id": "100:"},
    "1:101": {"parent": "1:10", "rate": "20Mbit", "ceil": "40Mbit",
              "burst": "2500b", "cburst": "5000b", "prio": 1,
              "quantum": 1500, "leaf_id": "101:"},
    "1:200": {"parent": "1:20", "rate": "15Mbit", "ceil": "40Mbit",
              "burst": "1875b", "cburst": "5000b", "prio": 2,
              "quantum": 1500, "leaf_id": "200:"},
    "1:201": {"parent": "1:20", "rate": "15Mbit", "ceil": "15Mbit",
              "burst": "1875b", "cburst": "1875b", "prio": 2,
              "quantum": 1500, "leaf_id": "201:"},
    "1:202": {"parent": "1:20", "rate": "10Mbit", "ceil": "30Mbit",
              "burst": "1250b", "cburst": "3750b", "prio": 2,
              "quantum": 1500, "leaf_id": "202:"},
    "1:300": {"parent": "1:30", "rate": "10Mbit", "ceil": "40Mbit",
              "burst": "1250b", "cburst": "5000b", "prio": 3,
              "quantum": 1500, "leaf_id": "300:"},
    "1:301": {"parent": "1:30", "rate": "10Mbit", "ceil": "20Mbit",
              "burst": "1250b", "cburst": "2500b", "prio": 3,
              "quantum": 60000, "leaf_id": "301:"},
}

INNER_CLASSES = {
    "1:1":  {"parent": None, "rate": "100Mbit", "ceil": "100Mbit",
             "burst": "12500b", "cburst": "12500b", "prio": None},
    "1:10": {"parent": "1:1", "rate": "40Mbit", "ceil": "100Mbit",
             "burst": "5000b", "cburst": "12500b", "prio": 1},
    "1:20": {"parent": "1:1", "rate": "40Mbit", "ceil": "80Mbit",
             "burst": "5000b", "cburst": "10000b", "prio": 2},
    "1:30": {"parent": "1:1", "rate": "20Mbit", "ceil": "60Mbit",
             "burst": "2500b", "cburst": "7500b", "prio": 3},
}

CHILDREN = {
    "1:1":  ["1:10", "1:20", "1:30"],
    "1:10": ["1:100", "1:101"],
    "1:20": ["1:200", "1:201", "1:202"],
    "1:30": ["1:300", "1:301"],
}

# Per-interval steady-state traffic for leaf classes
TRAFFIC = {
    "1:100": {"bps":   500_000, "drops_pkt":   0, "ol_pkt":   0, "backlog": 0},
    "1:101": {"bps": 4_000_000, "drops_pkt":   0, "ol_pkt":   0, "backlog": 0},
    "1:200": {"bps":10_000_000, "drops_pkt":   0, "ol_pkt":  20, "backlog": 0},
    "1:201": {"bps":15_000_000, "drops_pkt": 150, "ol_pkt":   0, "backlog": 15000},
    "1:202": {"bps": 6_000_000, "drops_pkt":   0, "ol_pkt":   0, "backlog": 0},
    "1:300": {"bps": 2_000_000, "drops_pkt":  80, "ol_pkt":   0, "backlog": 8000},
    "1:301": {"bps":18_000_000, "drops_pkt":   0, "ol_pkt": 800, "backlog": 0},
}

CLASS_ORDER = [
    "1:1", "1:10", "1:100", "1:101",
    "1:20", "1:200", "1:201", "1:202",
    "1:30", "1:300", "1:301",
]


def aggregate(cid, cum):
    if cid in LEAF_CLASSES:
        return {
            "bytes": cum[cid]["bytes"],
            "packets": cum[cid]["packets"],
            "drops": cum[cid]["drops"],
            "overlimits": cum[cid]["overlimits"],
            "backlog": TRAFFIC[cid]["backlog"],
        }
    total = {"bytes": 0, "packets": 0, "drops": 0, "overlimits": 0, "backlog": 0}
    for child in CHILDREN.get(cid, []):
        child_agg = aggregate(child, cum)
        for k in total:
            total[k] += child_agg[k]
    return total


def format_leaf_class(cid, cls, stats, backlog):
    lended = stats["packets"]
    borrowed = 0
    rate_bps = parse_rate(cls["rate"])
    actual_bps = TRAFFIC[cid]["bps"]
    if actual_bps > rate_bps:
        borrow_frac = (actual_bps - rate_bps) / actual_bps
        borrowed = int(stats["packets"] * borrow_frac)
        lended = stats["packets"] - borrowed
    bl_pkts = backlog // PKT_SIZE
    tok = 1000 if backlog == 0 else 0
    return (
        f"class htb {cid} parent {cls['parent']} leaf {cls['leaf_id']} "
        f"prio {cls['prio']} quantum {cls['quantum']} "
        f"rate {cls['rate']} ceil {cls['ceil']} "
        f"burst {cls['burst']} cburst {cls['cburst']} \n"
        f" Sent {stats['bytes']} bytes {stats['packets']} pkt "
        f"(dropped {stats['drops']}, overlimits {stats['overlimits']} requeues 0) \n"
        f" backlog {backlog}b {bl_pkts}p requeues 0 \n"
        f" lended: {lended} borrowed: {borrowed} giants: 0\n"
        f" tokens: {tok} ctokens: {tok}"
    )


def format_inner_class(cid, cls, agg):
    bl_pkts = agg["backlog"] // PKT_SIZE
    if cls["parent"] is None:
        header = (f"class htb {cid} root "
                  f"rate {cls['rate']} ceil {cls['ceil']} "
                  f"burst {cls['burst']} cburst {cls['cburst']} ")
    else:
        header = (f"class htb {cid} parent {cls['parent']} "
                  f"prio {cls['prio']} "
                  f"rate {cls['rate']} ceil {cls['ceil']} "
                  f"burst {cls['burst']} cburst {cls['cburst']} ")
    return (
        f"{header}\n"
        f" Sent {agg['bytes']} bytes {agg['packets']} pkt "
        f"(dropped {agg['drops']}, overlimits {agg['overlimits']} requeues 0) \n"
        f" backlog {agg['backlog']}b {bl_pkts}p requeues 0 \n"
        f" lended: {agg['packets'] // 2} borrowed: 0 giants: 0\n"
        f" tokens: 1000 ctokens: 1000"
    )


def generate_captures():
    os.makedirs(CAPTURE_DIR, exist_ok=True)

    cum = {}
    for cid in LEAF_CLASSES:
        t = TRAFFIC[cid]
        prior_bytes = int(t["bps"] * 60 / 8)
        prior_pkts = prior_bytes // PKT_SIZE
        cum[cid] = {
            "bytes": prior_bytes,
            "packets": prior_pkts,
            "drops": t["drops_pkt"] * 12,
            "overlimits": t["ol_pkt"] * 12,
        }

    for snap_idx in range(NUM_SNAPSHOTS):
        for cid in LEAF_CLASSES:
            t = TRAFFIC[cid]
            interval_bytes = int(t["bps"] * INTERVAL / 8)
            interval_pkts = interval_bytes // PKT_SIZE
            cum[cid]["bytes"] += interval_bytes
            cum[cid]["packets"] += interval_pkts
            cum[cid]["drops"] += t["drops_pkt"]
            cum[cid]["overlimits"] += t["ol_pkt"]

        entries = []
        for cid in CLASS_ORDER:
            if cid in LEAF_CLASSES:
                cls = LEAF_CLASSES[cid]
                stats = cum[cid]
                bl = TRAFFIC[cid]["backlog"]
                entries.append(format_leaf_class(cid, cls, stats, bl))
            else:
                cls = INNER_CLASSES[cid]
                agg = aggregate(cid, cum)
                entries.append(format_inner_class(cid, cls, agg))

        fname = os.path.join(CAPTURE_DIR, f"tc_dump_{snap_idx + 1:03d}.txt")
        with open(fname, "w") as f:
            f.write("\n\n".join(entries) + "\n")


def generate_filters():
    text = """\
filter parent 1:0 protocol ip pref 10 u32 chain 0
filter parent 1:0 protocol ip pref 10 u32 chain 0 fh 800: ht divisor 1
filter parent 1:0 protocol ip pref 10 u32 chain 0 fh 800::800 order 2048 key ht 0x800 bkt 0x0 flowid 1:100 not_in_hw
  match 00b00000/00fc0000 at 0
  (rule hit 0 success 0)

filter parent 1:0 protocol ip pref 20 u32 chain 0
filter parent 1:0 protocol ip pref 20 u32 chain 0 fh 801: ht divisor 1
filter parent 1:0 protocol ip pref 20 u32 chain 0 fh 801::800 order 2048 key ht 0x801 bkt 0x0 flowid 1:101 not_in_hw
  match 00a00000/00fc0000 at 0
  (rule hit 7500 success 7500)

filter parent 1:0 protocol ip pref 30 u32 chain 0
filter parent 1:0 protocol ip pref 30 u32 chain 0 fh 802: ht divisor 1
filter parent 1:0 protocol ip pref 30 u32 chain 0 fh 802::800 order 2048 key ht 0x802 bkt 0x0 flowid 1:200 not_in_hw
  match 00000cea/0000ffff at 20
  (rule hit 9000 success 9000)
filter parent 1:0 protocol ip pref 30 u32 chain 0 fh 802::801 order 2049 key ht 0x802 bkt 0x0 flowid 1:200 not_in_hw
  match 00001538/0000ffff at 20
  (rule hit 6000 success 6000)

filter parent 1:0 protocol ip pref 40 u32 chain 0
filter parent 1:0 protocol ip pref 40 u32 chain 0 fh 803: ht divisor 1
filter parent 1:0 protocol ip pref 40 u32 chain 0 fh 803::800 order 2048 key ht 0x803 bkt 0x0 flowid 1:201 not_in_hw
  match 00000050/0000ffff at 20
  (rule hit 15000 success 15000)
filter parent 1:0 protocol ip pref 40 u32 chain 0 fh 803::801 order 2049 key ht 0x803 bkt 0x0 flowid 1:201 not_in_hw
  match 000001bb/0000ffff at 20
  (rule hit 12000 success 12000)

filter parent 1:0 protocol ip pref 50 u32 chain 0
filter parent 1:0 protocol ip pref 50 u32 chain 0 fh 804: ht divisor 1
filter parent 1:0 protocol ip pref 50 u32 chain 0 fh 804::800 order 2048 key ht 0x804 bkt 0x0 flowid 1:202 not_in_hw
  match 00001f90/0000ffff at 20
  (rule hit 5000 success 5000)

filter parent 1:0 protocol ip pref 60 u32 chain 0
filter parent 1:0 protocol ip pref 60 u32 chain 0 fh 805: ht divisor 1
filter parent 1:0 protocol ip pref 60 u32 chain 0 fh 805::800 order 2048 key ht 0x805 bkt 0x0 flowid 1:301 not_in_hw
  match 00200000/00fc0000 at 0
  (rule hit 7500 success 7500)
"""
    with open("/app/filters.txt", "w") as f:
        f.write(text)


def generate_flows():
    rows = [
        ["flow_id", "src_ip", "dst_ip", "src_port", "dst_port",
         "proto", "dscp", "bytes_sent", "packets_sent", "expected_class"],
        ["F001", "10.1.1.10", "10.2.1.10", "16384", "5060",
         "UDP", "46", "2500000",  "2500",  "1:100"],
        ["F002", "10.1.1.11", "10.2.1.11", "16385", "5004",
         "UDP", "46", "8000000",  "8000",  "1:100"],
        ["F003", "10.1.1.12", "10.2.1.12", "16386", "5006",
         "UDP", "46", "3000000",  "3000",  "1:100"],
        ["F004", "10.1.1.20", "10.2.1.20", "16387", "5060",
         "UDP", "40", "4000000",  "4000",  "1:101"],
        ["F005", "10.1.1.21", "10.2.1.21", "16388", "5061",
         "UDP", "40", "3500000",  "3500",  "1:101"],
        ["F006", "10.1.1.30", "10.2.1.30", "49152", "3306",
         "TCP", "0",  "9000000",  "9000",  "1:200"],
        ["F007", "10.1.1.31", "10.2.1.31", "49153", "5432",
         "TCP", "0",  "6000000",  "6000",  "1:200"],
        ["F008", "10.1.1.40", "10.2.1.40", "49154", "80",
         "TCP", "0",  "15000000", "15000", "1:201"],
        ["F009", "10.1.1.41", "10.2.1.41", "49155", "443",
         "TCP", "0",  "12000000", "12000", "1:201"],
        ["F010", "10.1.1.50", "10.2.1.50", "49156", "8080",
         "TCP", "0",  "5000000",  "5000",  "1:202"],
        ["F011", "10.1.1.60", "10.2.1.60", "49157", "9090",
         "TCP", "0",  "3000000",  "3000",  "1:300"],
        ["F012", "10.1.1.61", "10.2.1.61", "49158", "22",
         "TCP", "0",  "2000000",  "2000",  "1:300"],
        ["F013", "10.1.1.70", "10.2.1.70", "49159", "6881",
         "TCP", "8",  "4000000",  "4000",  "1:301"],
        ["F014", "10.1.1.71", "10.2.1.71", "49160", "51413",
         "TCP", "8",  "3500000",  "3500",  "1:301"],
    ]
    with open("/app/flows.csv", "w", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)


def generate_sla():
    sla = {
        "1:100": {"min_throughput_bps": 20000000, "max_drop_rate": 0.001,
                   "name": "VoIP"},
        "1:101": {"min_throughput_bps": 20000000, "max_drop_rate": 0.001,
                   "name": "Signaling"},
        "1:200": {"min_throughput_bps": 15000000, "max_drop_rate": 0.01,
                   "name": "Database"},
        "1:201": {"min_throughput_bps": 15000000, "peak_throughput_bps": 30000000,
                   "max_drop_rate": 0.01, "name": "Web"},
        "1:202": {"min_throughput_bps": 10000000, "max_drop_rate": 0.01,
                   "name": "API"},
        "1:300": {"min_throughput_bps": 5000000, "name": "Bulk"},
        "1:301": {"min_throughput_bps": 5000000, "name": "Scavenger"},
    }
    with open("/app/sla.json", "w") as f:
        json.dump(sla, f, indent=2)


def generate_hierarchy():
    hierarchy = {
        "1:1":   {"parent": None,   "rate_bps": 100000000, "ceil_bps": 100000000,
                   "is_leaf": False, "name": "Root"},
        "1:10":  {"parent": "1:1",  "rate_bps":  40000000, "ceil_bps": 100000000,
                   "is_leaf": False, "name": "Critical"},
        "1:100": {"parent": "1:10", "rate_bps":  20000000, "ceil_bps":  40000000,
                   "is_leaf": True,  "name": "VoIP"},
        "1:101": {"parent": "1:10", "rate_bps":  20000000, "ceil_bps":  40000000,
                   "is_leaf": True,  "name": "Signaling"},
        "1:20":  {"parent": "1:1",  "rate_bps":  40000000, "ceil_bps":  80000000,
                   "is_leaf": False, "name": "Business"},
        "1:200": {"parent": "1:20", "rate_bps":  15000000, "ceil_bps":  40000000,
                   "is_leaf": True,  "name": "Database"},
        "1:201": {"parent": "1:20", "rate_bps":  15000000, "ceil_bps":  40000000,
                   "is_leaf": True,  "name": "Web"},
        "1:202": {"parent": "1:20", "rate_bps":  10000000, "ceil_bps":  30000000,
                   "is_leaf": True,  "name": "API"},
        "1:30":  {"parent": "1:1",  "rate_bps":  20000000, "ceil_bps":  60000000,
                   "is_leaf": False, "name": "BestEffort"},
        "1:300": {"parent": "1:30", "rate_bps":  10000000, "ceil_bps":  40000000,
                   "is_leaf": True,  "name": "Bulk"},
        "1:301": {"parent": "1:30", "rate_bps":  10000000, "ceil_bps":  20000000,
                   "is_leaf": True,  "name": "Scavenger"},
    }
    with open("/app/hierarchy.json", "w") as f:
        json.dump(hierarchy, f, indent=2)


if __name__ == "__main__":
    generate_captures()
    generate_filters()
    generate_flows()
    generate_sla()
    generate_hierarchy()
    print("Data generation complete.")
