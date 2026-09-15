#!/usr/bin/env python3
"""Generate firewall classification data: nftables ruleset, pcap, and
build-time verification of shadow/dependency/TR computations."""
import json
import random
import struct
import socket
import sys
from collections import Counter

random.seed(0xCAFEBABE)

# ===== IP Utility Functions =====

def ip_to_int(ip_str):
    parts = ip_str.split(".")
    return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])

def int_to_ip(ip_int):
    return f"{(ip_int>>24)&0xff}.{(ip_int>>16)&0xff}.{(ip_int>>8)&0xff}.{ip_int&0xff}"

def cidrs_overlap(cidr_a, cidr_b):
    net_a, plen_a = cidr_a.rsplit("/", 1)
    net_b, plen_b = cidr_b.rsplit("/", 1)
    plen_a, plen_b = int(plen_a), int(plen_b)
    if plen_a == 0 or plen_b == 0:
        return True
    a = ip_to_int(net_a)
    b = ip_to_int(net_b)
    min_p = min(plen_a, plen_b)
    shift = 32 - min_p
    return (a >> shift) == (b >> shift)

def cidr_contains(outer, inner):
    net_o, plen_o = outer.rsplit("/", 1)
    net_i, plen_i = inner.rsplit("/", 1)
    plen_o, plen_i = int(plen_o), int(plen_i)
    if plen_o == 0:
        return True
    if plen_i < plen_o:
        return False
    o = ip_to_int(net_o)
    i = ip_to_int(net_i)
    shift = 32 - plen_o
    return (o >> shift) == (i >> shift)

def port_range_contains(o_min, o_max, i_min, i_max):
    return o_min <= i_min and i_max <= o_max

def protocol_contains(outer, inner):
    if outer == "any":
        return True
    return outer == inner

def protocols_overlap(pa, pb):
    if pa == "any" or pb == "any":
        return True
    return pa == pb

def port_ranges_overlap(min_a, max_a, min_b, max_b):
    return min_a <= max_b and min_b <= max_a

def rule_is_superset(ra, rb):
    if not cidr_contains(ra["src_ip"], rb["src_ip"]):
        return False
    if not cidr_contains(ra["dst_ip"], rb["dst_ip"]):
        return False
    if not port_range_contains(ra["src_port_min"], ra["src_port_max"],
                                rb["src_port_min"], rb["src_port_max"]):
        return False
    if not port_range_contains(ra["dst_port_min"], ra["dst_port_max"],
                                rb["dst_port_min"], rb["dst_port_max"]):
        return False
    if not protocol_contains(ra["protocol"], rb["protocol"]):
        return False
    return True

def rules_overlap(ra, rb):
    if not cidrs_overlap(ra["src_ip"], rb["src_ip"]):
        return False
    if not cidrs_overlap(ra["dst_ip"], rb["dst_ip"]):
        return False
    if not port_ranges_overlap(ra["src_port_min"], ra["src_port_max"],
                                rb["src_port_min"], rb["src_port_max"]):
        return False
    if not port_ranges_overlap(ra["dst_port_min"], ra["dst_port_max"],
                                rb["dst_port_min"], rb["dst_port_max"]):
        return False
    if not protocols_overlap(ra["protocol"], rb["protocol"]):
        return False
    return True


# ===== Rule Generation =====
rules = []

# Phase A: 30 /24 ACCEPT exceptions (specific subnets, tcp/443)
for i in range(30):
    subnet = 100 + (i * 2)
    third = 10 + i
    rules.append({
        "id": len(rules),
        "src_ip": f"10.{subnet}.{third}.0/24",
        "dst_ip": "0.0.0.0/0",
        "src_port_min": 0, "src_port_max": 65535,
        "dst_port_min": 443, "dst_port_max": 443,
        "protocol": "tcp",
        "action": "accept",
    })

# Phase B: 60 /16 DROP rules (broad subnet blocks)
for i in range(60):
    rules.append({
        "id": len(rules),
        "src_ip": f"10.{100 + i}.0.0/16",
        "dst_ip": "0.0.0.0/0",
        "src_port_min": 0, "src_port_max": 65535,
        "dst_port_min": 0, "dst_port_max": 65535,
        "protocol": "any",
        "action": "drop",
    })

# Shadow group 1: 5 /24 DROP inside /16 DROP ranges
shadow_ids = []
for i in range(5):
    parent_subnet = 100 + (i * 10)
    rid = len(rules)
    shadow_ids.append(rid)
    rules.append({
        "id": rid,
        "src_ip": f"10.{parent_subnet}.{50 + i}.0/24",
        "dst_ip": "0.0.0.0/0",
        "src_port_min": 0, "src_port_max": 65535,
        "dst_port_min": 0, "dst_port_max": 65535,
        "protocol": "any",
        "action": "drop",
    })

# Phase C: 250 specific host ACCEPT rules (safe subnets 10.5-14.x.x)
services = [
    (80, 80, "tcp"), (443, 443, "tcp"), (8080, 8080, "tcp"),
    (53, 53, "udp"), (22, 22, "tcp"), (3306, 3306, "tcp"),
    (5432, 5432, "tcp"), (6379, 6379, "tcp"), (8443, 8443, "tcp"),
    (9090, 9090, "tcp"),
]
phase3_start = len(rules)  # 95
for i in range(250):
    second_octet = 5 + (i // 25)
    third_octet = (i * 7 + 3) % 256
    fourth_octet = (i * 13 + 1) % 254 + 1
    service = services[i % len(services)]
    rules.append({
        "id": len(rules),
        "src_ip": f"10.{second_octet}.{third_octet}.{fourth_octet}/32",
        "dst_ip": "0.0.0.0/0",
        "src_port_min": 0, "src_port_max": 65535,
        "dst_port_min": service[0], "dst_port_max": service[1],
        "protocol": service[2],
        "action": "accept",
    })

# Shadow group 2: 5 rules with restricted dst (shadowed by Phase C parents)
for i in range(5):
    parent_idx = phase3_start + i * 40
    parent = rules[parent_idx]
    rid = len(rules)
    shadow_ids.append(rid)
    rules.append({
        "id": rid,
        "src_ip": parent["src_ip"],
        "dst_ip": f"192.168.{i}.0/24",
        "src_port_min": parent["src_port_min"], "src_port_max": parent["src_port_max"],
        "dst_port_min": parent["dst_port_min"], "dst_port_max": parent["dst_port_max"],
        "protocol": parent["protocol"],
        "action": "accept",
    })

# Phase D: 40 LOG rules (172.16.0-39.0/24)
phase4_start = len(rules)  # 350
for i in range(40):
    rules.append({
        "id": len(rules),
        "src_ip": f"172.16.{i}.0/24",
        "dst_ip": "0.0.0.0/0",
        "src_port_min": 0, "src_port_max": 65535,
        "dst_port_min": 0, "dst_port_max": 65535,
        "protocol": "any",
        "action": "log",
    })

# Shadow group 3: 5 /28 LOG inside /24 LOG
for i in range(5):
    parent_third = i * 7
    rid = len(rules)
    shadow_ids.append(rid)
    rules.append({
        "id": rid,
        "src_ip": f"172.16.{parent_third}.0/28",
        "dst_ip": "0.0.0.0/0",
        "src_port_min": 0, "src_port_max": 65535,
        "dst_port_min": 0, "dst_port_max": 65535,
        "protocol": "any",
        "action": "log",
    })

# Phase E: 25 port-based DROP rules (dangerous ports)
dangerous_ports = [23, 25, 135, 137, 138, 139, 445, 1433, 1434, 3389,
                   4444, 5900, 5901, 6660, 6661, 6662, 6663, 6664, 6665, 6666,
                   6667, 6668, 6669, 1080, 8888]
for port in dangerous_ports:
    rules.append({
        "id": len(rules),
        "src_ip": "0.0.0.0/0",
        "dst_ip": "0.0.0.0/0",
        "src_port_min": 0, "src_port_max": 65535,
        "dst_port_min": port, "dst_port_max": port,
        "protocol": "tcp",
        "action": "drop",
    })

# Default ACCEPT
rules.append({
    "id": len(rules),
    "src_ip": "0.0.0.0/0",
    "dst_ip": "0.0.0.0/0",
    "src_port_min": 0, "src_port_max": 65535,
    "dst_port_min": 0, "dst_port_max": 65535,
    "protocol": "any",
    "action": "accept",
})

shadow_ids.sort()
print(f"Generated {len(rules)} rules")
print(f"Shadow IDs: {shadow_ids}")

# ===== Verify Shadows (programmatic) =====
computed_shadows = []
for j in range(len(rules)):
    for i in range(j):
        if rule_is_superset(rules[i], rules[j]):
            computed_shadows.append(rules[j]["id"])
            break
computed_shadows.sort()
assert computed_shadows == shadow_ids, f"Shadow mismatch: {computed_shadows} vs {shadow_ids}"
print(f"Shadow verification passed: {len(computed_shadows)} shadows")

# ===== Compute Dependencies (build-time verification only) =====
deps = []
for i in range(len(rules)):
    for j in range(i + 1, len(rules)):
        if rules[i]["action"] != rules[j]["action"]:
            if rules_overlap(rules[i], rules[j]):
                deps.append([rules[i]["id"], rules[j]["id"]])
print(f"Computed {len(deps)} dependency edges")

# ===== Compute Transitive Reduction (build-time verification only) =====
all_ids = set(r["id"] for r in rules)
adj = {n: set() for n in all_ids}
for a, b in deps:
    adj[a].add(b)

tr_edges = []
for u, v in deps:
    reachable = set()
    queue = []
    for w in adj[u]:
        if w != v and w not in reachable:
            reachable.add(w)
            queue.append(w)
    idx = 0
    while idx < len(queue):
        node = queue[idx]
        idx += 1
        for neighbor in adj[node]:
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)
    if v not in reachable:
        tr_edges.append([u, v])

print(f"Transitive reduction: {len(tr_edges)} edges (removed {len(deps) - len(tr_edges)})")

# ===== Write nftables Ruleset =====
def rule_to_nft_line(rule):
    parts = []
    if rule["src_ip"] != "0.0.0.0/0":
        parts.append(f"ip saddr {rule['src_ip']}")
    if rule["dst_ip"] != "0.0.0.0/0":
        parts.append(f"ip daddr {rule['dst_ip']}")
    proto = rule["protocol"]
    if proto != "any":
        if rule["src_port_min"] != 0 or rule["src_port_max"] != 65535:
            if rule["src_port_min"] == rule["src_port_max"]:
                parts.append(f"{proto} sport {rule['src_port_min']}")
            else:
                parts.append(f"{proto} sport {rule['src_port_min']}-{rule['src_port_max']}")
        if rule["dst_port_min"] != 0 or rule["dst_port_max"] != 65535:
            if rule["dst_port_min"] == rule["dst_port_max"]:
                parts.append(f"{proto} dport {rule['dst_port_min']}")
            else:
                parts.append(f"{proto} dport {rule['dst_port_min']}-{rule['dst_port_max']}")
    parts.append(f"counter {rule['action']}")
    return "        " + " ".join(parts)

nft_lines = [
    "#!/usr/sbin/nft -f",
    "# Firewall classification ruleset -- production export",
    "# Chain: classify (inet family, filter hook)",
    "",
    "flush ruleset",
    "",
    "table inet firewall {",
    "    chain classify {",
    "        type filter hook input priority filter; policy accept;",
    "",
]

phase_headers = {
    0: "        # --- Service exceptions (HTTPS allow-list) ---",
    30: "        # --- Subnet security boundaries (/16 enforcement) ---",
    90: "        # --- Supplemental subnet enforcement ---",
    phase3_start: "        # --- Per-host service policies ---",
    phase3_start + 250: "        # --- Supplemental service rules ---",
    phase4_start: "        # --- Network monitoring ---",
    phase4_start + 40: "        # --- Supplemental monitoring ---",
    phase4_start + 45: "        # --- Port-based security ---",
    len(rules) - 1: "        # --- Default policy ---",
}

for rule in rules:
    if rule["id"] in phase_headers:
        nft_lines.append(phase_headers[rule["id"]])
    nft_lines.append(f"        # rule_id={rule['id']}")
    nft_lines.append(rule_to_nft_line(rule))
    nft_lines.append("")

nft_lines.extend(["    }", "}"])

with open("/app/firewall.nft", "w") as f:
    f.write("\n".join(nft_lines) + "\n")
print("Wrote firewall.nft")

# ===== Traffic Generation =====
phase3_indices = list(range(phase3_start, phase3_start + 250))
phase_a_hot = sorted(random.sample(phase3_indices[:125], 10))
phase_b_hot = sorted(random.sample(phase3_indices[125:], 10))
phase1_indices = list(range(0, 30))
phase4_indices = list(range(phase4_start, phase4_start + 40))
phase_c_hot = sorted(random.sample(phase1_indices, 5) + random.sample(phase4_indices, 5))

print(f"Phase A hot rule indices: {phase_a_hot}")
print(f"Phase B hot rule indices: {phase_b_hot}")
print(f"Phase C hot rule indices: {phase_c_hot}")

def generate_matching_packet(rule_idx):
    rule = rules[rule_idx]
    src_net, src_plen = rule["src_ip"].rsplit("/", 1)
    src_plen = int(src_plen)
    if src_plen == 32:
        src_ip = src_net
    elif src_plen == 0:
        src_ip = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
    else:
        src_base = ip_to_int(src_net)
        host_bits = 32 - src_plen
        max_host = (1 << host_bits) - 2
        random_host = random.randint(1, max(1, max_host))
        src_int = src_base | random_host
        src_ip = int_to_ip(src_int)

    dst_net, dst_plen = rule["dst_ip"].rsplit("/", 1)
    dst_plen = int(dst_plen)
    if dst_plen == 0:
        dst_ip = f"192.168.{random.randint(0,255)}.{random.randint(1,254)}"
    else:
        dst_base = ip_to_int(dst_net)
        host_bits = 32 - dst_plen
        max_host = (1 << host_bits) - 2
        random_host = random.randint(1, max(1, max_host))
        dst_int = dst_base | random_host
        dst_ip = int_to_ip(dst_int)

    if rule["protocol"] == "any":
        proto = random.choice(["tcp", "udp"])
    else:
        proto = rule["protocol"]

    src_port = random.randint(1024, 65535)
    dst_port = random.randint(rule["dst_port_min"], rule["dst_port_max"])

    return {
        "src_ip": src_ip, "dst_ip": dst_ip,
        "src_port": src_port, "dst_port": dst_port,
        "protocol": proto
    }

def generate_cold_packet():
    # Cold traffic from blocked /16 subnets — matches Phase 2 DROP rules
    # (not tcp/443 so it doesn't match Phase 1 exceptions)
    second = random.randint(100, 159)
    return {
        "src_ip": f"10.{second}.{random.randint(0,255)}.{random.randint(1,254)}",
        "dst_ip": f"192.168.{random.randint(0,255)}.{random.randint(1,254)}",
        "src_port": random.randint(1024, 65535),
        "dst_port": random.choice([80, 8080, 22, 3306, 5432, 9090]),
        "protocol": random.choice(["tcp", "udp"])
    }

packets = []
weights = [1.0 / (i + 1) for i in range(10)]

# Phase A: 15000 packets targeting Phase C host rules (first half)
for _ in range(15000):
    if random.random() < 0.9:
        rank = random.choices(range(10), weights=weights, k=1)[0]
        packets.append(generate_matching_packet(phase_a_hot[rank]))
    else:
        packets.append(generate_cold_packet())

# Phase B: 15000 packets targeting Phase C host rules (second half)
for _ in range(15000):
    if random.random() < 0.9:
        rank = random.choices(range(10), weights=weights, k=1)[0]
        packets.append(generate_matching_packet(phase_b_hot[rank]))
    else:
        packets.append(generate_cold_packet())

# Phase C: 15000 packets targeting exceptions + monitoring rules
for _ in range(15000):
    if random.random() < 0.9:
        rank = random.choices(range(10), weights=weights, k=1)[0]
        packets.append(generate_matching_packet(phase_c_hot[rank]))
    else:
        packets.append(generate_cold_packet())

print(f"Generated {len(packets)} packets in 3 phases")

# ===== Write PCAP (linktype 101 = Raw IPv4) =====
def ip_checksum(header_bytes):
    if len(header_bytes) % 2:
        header_bytes += b'\x00'
    total = 0
    for i in range(0, len(header_bytes), 2):
        total += (header_bytes[i] << 8) + header_bytes[i + 1]
    while total > 0xffff:
        total = (total >> 16) + (total & 0xffff)
    return ~total & 0xffff

def make_raw_ip_packet(pkt):
    src = socket.inet_aton(pkt["src_ip"])
    dst = socket.inet_aton(pkt["dst_ip"])
    proto_num = 6 if pkt["protocol"] == "tcp" else 17
    if proto_num == 6:
        transport = struct.pack('!HHIIBBHHH',
                                pkt["src_port"], pkt["dst_port"],
                                0, 0, (5 << 4), 0x02, 65535, 0, 0)
    else:
        transport = struct.pack('!HHHH',
                                pkt["src_port"], pkt["dst_port"], 8, 0)
    total_len = 20 + len(transport)
    ip_hdr_no_cksum = struct.pack('!BBHHHBBH',
                                   0x45, 0, total_len, 0, 0x4000,
                                   64, proto_num, 0) + src + dst
    cksum = ip_checksum(ip_hdr_no_cksum)
    ip_hdr = struct.pack('!BBHHHBBH',
                          0x45, 0, total_len, 0, 0x4000,
                          64, proto_num, cksum) + src + dst
    return ip_hdr + transport

with open("/app/traffic.pcap", "wb") as f:
    f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 101))
    timestamp = 1700000000.0
    for pkt in packets:
        raw = make_raw_ip_packet(pkt)
        ts_sec = int(timestamp)
        ts_usec = int((timestamp - ts_sec) * 1e6)
        f.write(struct.pack('<IIII', ts_sec, ts_usec, len(raw), len(raw)))
        f.write(raw)
        timestamp += 0.001

print("Wrote traffic.pcap")

# ===== Run Baseline Verification =====
sys.path.insert(0, '/app')
from baseline_classifier import BaselineClassifier
baseline = BaselineClassifier("/app/firewall.nft")
hit_counts = Counter()
for pkt in packets:
    action, rule_id = baseline.classify(pkt)
    hit_counts[rule_id] += 1

print(f"Baseline classification complete")
print(f"Top 10 hit rules: {hit_counts.most_common(10)}")

# Verify phase structure
for phase_name, start_idx, end_idx in [("A", 0, 15000), ("B", 15000, 30000), ("C", 30000, 45000)]:
    phase_hits = Counter()
    for pkt in packets[start_idx:end_idx]:
        _, rid = baseline.classify(pkt)
        phase_hits[rid] += 1
    top = [rid for rid, _ in phase_hits.most_common(5)]
    print(f"Phase {phase_name} top 5 rules: {top}")

print(f"Build verification: {len(shadow_ids)} shadows, {len(deps)} deps, {len(tr_edges)} TR edges")
print("Data generation complete")
