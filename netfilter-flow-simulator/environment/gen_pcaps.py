#!/usr/bin/env python3
"""Generate pcap files for netfilter forensics incidents."""
import os
import logging
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

from scapy.all import IP, TCP, wrpcap, conf
conf.verb = 0

INCIDENTS_DIR = "/app/incidents"


def tcp_syn(src, sport, dst, dport):
    return IP(src=src, dst=dst) / TCP(sport=sport, dport=dport, flags="S")


def gen_basic_flow():
    return [tcp_syn("198.18.0.2", 10000 + i, "192.0.2.1", 80) for i in range(10)]


def gen_conntrack_overflow():
    return [tcp_syn("198.18.0.2", 10000 + i, "192.0.2.1", 80) for i in range(10)]


def gen_notrack_bypass():
    pkts = []
    pkts += [tcp_syn("198.18.0.2", 10000 + i, "192.0.2.1", 80) for i in range(5)]
    pkts += [tcp_syn("198.18.0.2", 20000 + i, "192.0.2.1", 443) for i in range(5)]
    pkts += [tcp_syn("198.18.0.2", 10005 + i, "192.0.2.1", 80) for i in range(5)]
    return pkts


def gen_drop_no_confirm():
    return [tcp_syn("198.18.0.2", 10000 + i, "192.0.2.1", 80) for i in range(10)]


def gen_mixed_complex():
    pkts = []
    pkts += [tcp_syn("198.18.0.{}".format(i + 1), 40000 + i, "192.0.2.1", 80) for i in range(5)]
    pkts += [tcp_syn("198.18.1.{}".format(i + 1), 50000 + i, "192.0.2.1", 22) for i in range(3)]
    pkts += [tcp_syn("198.18.2.{}".format(i + 1), 60000 + i, "192.0.2.1", 443) for i in range(3)]
    pkts += [tcp_syn("198.18.0.{}".format(i + 6), 40005 + i, "192.0.2.1", 80) for i in range(5)]
    return pkts


def gen_duplicate_flows():
    pkts = []
    pkts += [tcp_syn("198.18.0.2", 10000 + i, "192.0.2.1", 80) for i in range(5)]
    pkts += [tcp_syn("198.18.0.2", 10000 + i, "192.0.2.1", 80) for i in range(5)]
    pkts += [tcp_syn("198.18.0.2", 10005 + i, "192.0.2.1", 80) for i in range(3)]
    return pkts


SCENARIOS = {
    "basic_flow": gen_basic_flow,
    "conntrack_overflow": gen_conntrack_overflow,
    "notrack_bypass": gen_notrack_bypass,
    "drop_no_confirm": gen_drop_no_confirm,
    "mixed_complex": gen_mixed_complex,
    "duplicate_flows": gen_duplicate_flows,
}

if __name__ == "__main__":
    os.makedirs(INCIDENTS_DIR, exist_ok=True)
    for name, gen_fn in SCENARIOS.items():
        pkts = gen_fn()
        path = os.path.join(INCIDENTS_DIR, "{}.pcap".format(name))
        wrpcap(path, pkts)
        print("Generated {}.pcap ({} packets)".format(name, len(pkts)))
