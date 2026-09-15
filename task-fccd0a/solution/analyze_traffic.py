#!/usr/bin/env python3
"""Analyze traffic.pcap using tshark and produce /app/traffic_analysis.json."""

import subprocess
import json
from collections import Counter

# Extract packet fields via tshark
result = subprocess.run(
    ['tshark', '-r', '/app/traffic.pcap', '-T', 'fields',
     '-e', 'ip.src', '-e', 'ip.dst', '-e', 'ip.proto',
     '-e', 'tcp.srcport', '-e', 'tcp.dstport',
     '-e', 'udp.srcport', '-e', 'udp.dstport',
     '-E', 'separator=|'],
    capture_output=True, text=True
)

src_ips = Counter()
dst_ports = Counter()
protocols = Counter()
total = 0

for line in result.stdout.strip().split('\n'):
    if not line.strip():
        continue
    total += 1
    fields = line.split('|')
    src_ip = fields[0]
    proto_num = fields[2]

    src_ips[src_ip] += 1

    proto_name = "tcp" if proto_num == "6" else "udp" if proto_num == "17" else "other"
    protocols[proto_name] += 1

    # Destination port: tcp.dstport (field 4) or udp.dstport (field 6)
    tcp_dport = fields[4] if len(fields) > 4 else ""
    udp_dport = fields[6] if len(fields) > 6 else ""
    dport = tcp_dport or udp_dport
    if dport:
        dst_ports[int(dport)] += 1

analysis = {
    "total_packets": total,
    "protocol_distribution": dict(protocols),
    "top_src_ips": [{"ip": ip, "count": cnt} for ip, cnt in src_ips.most_common(20)],
    "top_dst_ports": [{"port": port, "count": cnt} for port, cnt in dst_ports.most_common(20)]
}

with open("/app/traffic_analysis.json", "w") as f:
    json.dump(analysis, f, indent=2)

print(f"Traffic analysis complete: {total} packets analyzed")
print(f"Protocol distribution: {dict(protocols)}")
print(f"Top 5 source IPs: {src_ips.most_common(5)}")
print(f"Top 5 dst ports: {dst_ports.most_common(5)}")
