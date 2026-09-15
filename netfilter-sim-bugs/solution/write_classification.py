#!/usr/bin/env python3
"""
Create attack traffic classification from pcap analysis.

Identifies three attack vectors:
  1. SYN flood from 198.18.0.0/15 targeting port 80
  2. DNS amplification: UDP src port 53 with large payloads (> 200 bytes)
  3. Port scan from 192.168.100.0/24
"""

import json
import os


def write_classification():
    classification = {
        "attack_patterns": [
            {
                "name": "syn_flood",
                "criteria": {
                    "protocol": "tcp",
                    "src_network": "198.18.0.0/15",
                    "dst_port": 80
                }
            },
            {
                "name": "dns_amplification",
                "criteria": {
                    "protocol": "udp",
                    "src_port": 53,
                    "min_payload_length": 200
                }
            },
            {
                "name": "port_scan",
                "criteria": {
                    "protocol": "tcp",
                    "src_network": "192.168.100.0/24"
                }
            }
        ]
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/classification.json", "w") as f:
        json.dump(classification, f, indent=2)

    print("Wrote /app/output/classification.json with 3 attack patterns:")
    print("  - syn_flood: TCP to port 80 from 198.18.0.0/15")
    print("  - dns_amplification: UDP src port 53, payload > 200 bytes")
    print("  - port_scan: TCP from 192.168.100.0/24")


if __name__ == "__main__":
    write_classification()
