#!/usr/bin/env python3
"""
Analyze traffic mix and design optimal DDoS mitigation rules.

Analyzes /app/traffic_mix.json to identify attack patterns and designs
iptables rules that:
  - Drop all attack traffic, accept all legitimate traffic
  - Keep conntrack entries <= 120 (via NOTRACK for DNS)
  - Achieve >= 60% of drops in raw PREROUTING (performance)
"""

import json
import os
from collections import Counter, defaultdict
from ipaddress import ip_address, ip_network


def analyze_and_design():
    with open("/app/traffic_mix.json") as f:
        data = json.load(f)

    packets = data["packets"]
    conntrack_max = data["conntrack_max"]
    print("Loaded {} packets, conntrack_max={}".format(len(packets), conntrack_max))

    # Analyze TCP traffic by destination port and source networks
    tcp_by_dstport = defaultdict(list)
    for pkt in packets:
        if pkt["protocol"] == "TCP":
            tcp_by_dstport[pkt["dst_port"]].append(pkt["src_ip"])

    print("\nTCP traffic breakdown:")
    for port in sorted(tcp_by_dstport.keys(),
                       key=lambda p: -len(tcp_by_dstport[p])):
        srcs = tcp_by_dstport[port]
        src_nets = Counter()
        for ip in srcs:
            octets = ip.split(".")
            prefix = "{}.{}.0.0/16".format(octets[0], octets[1])
            src_nets[prefix] += 1
        top_net = src_nets.most_common(1)[0] if src_nets else ("?", 0)
        print("  port {}: {} packets (top source: {} with {})".format(
            port, len(srcs), top_net[0], top_net[1]))

    # Identify SYN flood: massive TCP to port 80 from concentrated range
    syn_flood_net = None
    if 80 in tcp_by_dstport:
        flood_ips = set(tcp_by_dstport[80])
        # Check 198.18.0.0/15
        net = ip_network("198.18.0.0/15", strict=False)
        covered = sum(1 for ip in flood_ips if ip_address(ip) in net)
        if covered == len(flood_ips):
            syn_flood_net = "198.18.0.0/15"
            print("\nSYN flood identified: {} packets from {}".format(
                len(flood_ips), syn_flood_net))

    # Identify port scan: TCP to many different high ports from single range
    high_port_srcs = defaultdict(set)
    for pkt in packets:
        if pkt["protocol"] == "TCP" and pkt["dst_port"] not in (22, 80, 443):
            high_port_srcs[pkt["src_ip"]].add(pkt["dst_port"])

    scan_ips = set(high_port_srcs.keys())
    scan_net = None
    if scan_ips:
        net = ip_network("192.168.100.0/24", strict=False)
        covered = sum(1 for ip in scan_ips if ip_address(ip) in net)
        if covered == len(scan_ips):
            scan_net = "192.168.100.0/24"
            total_scan = sum(
                1 for pkt in packets
                if pkt["protocol"] == "TCP"
                and ip_address(pkt["src_ip"]) in net)
            print("Port scan identified: {} packets from {}".format(
                total_scan, scan_net))

    # Analyze DNS (UDP src_port 53)
    dns_sources = Counter()
    for pkt in packets:
        if pkt["protocol"] == "UDP" and pkt["src_port"] == 53:
            dns_sources[pkt["src_ip"]] += 1

    total_dns = sum(dns_sources.values())
    unique_dns = len(dns_sources)
    print("\nDNS traffic (UDP src_port 53): {} packets from {} sources".format(
        total_dns, unique_dns))

    # Resolvers: IPs appearing multiple times (legitimate)
    # Amplification: IPs appearing once (scattered reflectors)
    resolvers = sorted(ip for ip, count in dns_sources.items() if count >= 3)
    amp_count = sum(1 for ip, count in dns_sources.items() if count < 3)
    print("  Resolvers (>= 3 packets each): {}".format(resolvers))
    print("  Amplification sources: {} unique IPs".format(amp_count))

    # Design rules
    rules = []

    # 1. Drop SYN flood in raw PREROUTING (before conntrack)
    if syn_flood_net:
        rules.append({
            "table": "raw", "chain": "PREROUTING",
            "src_network": syn_flood_net, "action": "DROP"
        })

    # 2. Drop port scan in raw PREROUTING
    if scan_net:
        rules.append({
            "table": "raw", "chain": "PREROUTING",
            "src_network": scan_net, "action": "DROP"
        })

    # 3. NOTRACK all DNS (src_port 53) to avoid wasting conntrack slots
    rules.append({
        "table": "raw", "chain": "PREROUTING",
        "src_port": 53, "action": "NOTRACK"
    })

    # 4. Whitelist known resolvers in filter INPUT (order matters!)
    for resolver_ip in resolvers:
        rules.append({
            "table": "filter", "chain": "INPUT",
            "protocol": "UDP", "src_port": 53,
            "src_ip": resolver_ip, "action": "ACCEPT"
        })

    # 5. Drop all remaining UDP from port 53 (amplification)
    rules.append({
        "table": "filter", "chain": "INPUT",
        "protocol": "UDP", "src_port": 53,
        "action": "DROP"
    })

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/rules.json", "w") as f:
        json.dump(rules, f, indent=2)

    print("\nWrote {} rules to /app/output/rules.json".format(len(rules)))

    # Verify expected performance
    raw_drops = 0
    filter_drops = 0
    if syn_flood_net:
        raw_drops += len(tcp_by_dstport.get(80, []))
    if scan_net:
        raw_drops += sum(
            1 for pkt in packets
            if pkt["protocol"] == "TCP"
            and ip_address(pkt["src_ip"]) in ip_network(scan_net, strict=False))
    filter_drops = amp_count
    total_drops = raw_drops + filter_drops
    legit_tcp = sum(
        1 for pkt in packets
        if pkt["protocol"] == "TCP"
        and pkt["dst_port"] in (22, 443)
        and not ip_address(pkt["src_ip"]) in ip_network("192.168.100.0/24", strict=False))

    print("\nExpected performance:")
    print("  Raw drops: {} ({:.1%} of total)".format(
        raw_drops, raw_drops / total_drops if total_drops else 0))
    print("  Filter drops: {}".format(filter_drops))
    print("  Conntrack entries: {} (TCP only, DNS NOTRACK'd)".format(legit_tcp))


if __name__ == "__main__":
    analyze_and_design()
