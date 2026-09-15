#!/usr/bin/env python3
"""Analyze ruleset and traffic to produce /app/ruleset_analysis.json."""

import sys
import json
import struct
from collections import Counter

sys.path.insert(0, '/app')
from optimized_classifier import AdaptiveClassifier


def read_packets_from_pcap(path):
    packets = []
    with open(path, 'rb') as f:
        f.read(24)  # skip global header
        while True:
            hdr = f.read(16)
            if len(hdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', hdr)
            data = f.read(incl_len)
            if len(data) < 20:
                continue
            ihl = (data[0] & 0x0f) * 4
            proto_num = data[9]
            src_ip = f"{data[12]}.{data[13]}.{data[14]}.{data[15]}"
            dst_ip = f"{data[16]}.{data[17]}.{data[18]}.{data[19]}"
            transport = data[ihl:]
            if len(transport) < 4:
                continue
            src_port = struct.unpack('!H', transport[0:2])[0]
            dst_port = struct.unpack('!H', transport[2:4])[0]
            proto_name = "tcp" if proto_num == 6 else "udp" if proto_num == 17 else "other"
            packets.append({
                "src_ip": src_ip, "dst_ip": dst_ip,
                "src_port": src_port, "dst_port": dst_port,
                "protocol": proto_name
            })
    return packets


# Load classifier
classifier = AdaptiveClassifier("/app/firewall.nft")

# Read traffic
packets = read_packets_from_pcap("/app/traffic.pcap")
print(f"Read {len(packets)} packets")

# Classify all packets and collect hit counts
hit_counts = Counter()
results = []
for pkt in packets:
    action, rule_id = classifier.classify(pkt)
    results.append(rule_id)
    hit_counts[rule_id] += 1

# Detect phase boundaries via sliding window distribution analysis
window = 1000
step = 200
dissimilarities = []

for i in range(0, len(results) - window * 2, step):
    window_a = Counter(results[i:i + window])
    window_b = Counter(results[i + window:i + window * 2])
    all_keys = set(window_a.keys()) | set(window_b.keys())
    # Compute Jaccard distance on top-10 rule sets
    top_a = set(k for k, _ in window_a.most_common(10))
    top_b = set(k for k, _ in window_b.most_common(10))
    if len(top_a | top_b) > 0:
        jaccard = 1.0 - len(top_a & top_b) / len(top_a | top_b)
    else:
        jaccard = 0.0
    dissimilarities.append((i + window, jaccard))

# Find peaks (phase boundaries)
threshold = 0.5
candidates = [(pos, score) for pos, score in dissimilarities if score >= threshold]

# Cluster candidates into 2 boundaries
if len(candidates) >= 2:
    boundaries = []
    current_cluster = [candidates[0]]
    for pos, score in candidates[1:]:
        if pos - current_cluster[-1][0] < 3000:
            current_cluster.append((pos, score))
        else:
            best = max(current_cluster, key=lambda x: x[1])
            boundaries.append(best[0])
            current_cluster = [(pos, score)]
    best = max(current_cluster, key=lambda x: x[1])
    boundaries.append(best[0])
    boundaries = sorted(boundaries[:2])
else:
    boundaries = [15000, 30000]

print(f"Detected phase boundaries: {boundaries}")

# Build analysis
unreachable = classifier.get_unreachable_rules()
ordering_constraints = classifier.get_ordering_constraints()
minimal_constraints = classifier.get_minimal_constraints()

top_hits = dict(hit_counts.most_common(30))

analysis = {
    "total_rules": len(classifier._original_rules),
    "unreachable_rule_ids": unreachable,
    "ordering_constraint_count": len(ordering_constraints),
    "minimal_constraint_count": len(minimal_constraints),
    "phase_boundaries": boundaries,
    "per_rule_hit_counts": {str(rid): cnt for rid, cnt in sorted(top_hits.items(), key=lambda x: -x[1])},
}

with open("/app/ruleset_analysis.json", "w") as f:
    json.dump(analysis, f, indent=2)

print(f"Analysis written to /app/ruleset_analysis.json")
print(f"  Total rules: {analysis['total_rules']}")
print(f"  Unreachable: {len(unreachable)}")
print(f"  Ordering constraints: {len(ordering_constraints)}")
print(f"  Minimal constraints: {len(minimal_constraints)}")
print(f"  Boundaries: {boundaries}")
