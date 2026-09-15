#!/usr/bin/env python3
"""
Analyze incident.pcap using tshark and produce traffic_stats.json.

"""

import json
import os
import subprocess
from collections import Counter


def tshark_extract(pcap, display_filter, field):
    """Run tshark to extract a single field from matching packets."""
    result = subprocess.run(
        ["tshark", "-r", pcap, "-Y", display_filter,
         "-T", "fields", "-e", field],
        capture_output=True, text=True,
    )
    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return lines


def main():
    pcap = "/app/captures/incident.pcap"

    # Request packets: UDP dst port 80
    req_sources = tshark_extract(pcap, "udp.dstport==80", "ip.src")
    total_requests = len(req_sources)
    unique_client_ips = len(set(req_sources))

    # Response packets: UDP src port 80
    resp_sources = tshark_extract(pcap, "udp.srcport==80", "ip.src")
    total_responses = len(resp_sources)

    # Backend distribution
    dist = dict(Counter(resp_sources))
    most_loaded = max(dist, key=dist.get) if dist else ""

    stats = {
        "total_requests": total_requests,
        "total_responses": total_responses,
        "backend_distribution": dist,
        "most_loaded_backend": most_loaded,
        "unique_client_ips": unique_client_ips,
    }

    os.makedirs("/app/analysis", exist_ok=True)
    with open("/app/analysis/traffic_stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
