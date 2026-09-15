#!/usr/bin/env python3
"""Policy diagnosis tool for the Cilium datapath simulator.

Usage: python3 /app/tools/diagnose.py <src_ip> <dst_ip> <sport> <dport> <proto>

Evaluates a packet against loaded policies and prints verdict details.
Useful for debugging policy enforcement and identity resolution.
"""

import sys
import os
sys.path.insert(0, '/app')

from datapath import Packet, load_config


def format_verdict(verdict_code):
    """Format verdict code for human-readable display."""
    labels = {
        0: "PASS (CTX_ACT_OK)",
        7: "REDIRECT (CTX_ACT_REDIRECT)",
        -2: "DROP (INVALID)",
        -173: "DROP (NO_POLICY)",
        -186: "DROP (NO_SERVICE)",
        -153: "DROP (UNKNOWN_CT)",
    }
    return labels.get(verdict_code, f"PASS (code={verdict_code})")


def main():
    if len(sys.argv) != 6:
        print(f"Usage: {sys.argv[0]} <src_ip> <dst_ip> <sport> <dport> <proto>")
        sys.exit(1)

    engine = load_config('/app/config.json')
    pkt = Packet(sys.argv[1], sys.argv[2],
                 int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]))

    result = engine.process_packet(pkt)

    print(f"Packet: {pkt.saddr}:{pkt.sport} -> {pkt.daddr}:{pkt.dport} proto={pkt.protocol}")
    print(f"Verdict: {format_verdict(result.verdict)}")
    print(f"CT Status: {result.ct_status}")
    print(f"Dst Identity: 0x{result.dst_identity:04x}")
    print(f"Proxy Port: {result.proxy_port}")
    print(f"Hairpin: {result.hairpin}")
    print(f"Loopback: {result.loopback}")


if __name__ == "__main__":
    main()
