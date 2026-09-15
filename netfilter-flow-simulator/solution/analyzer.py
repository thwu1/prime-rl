#!/usr/bin/env python3
"""
Netfilter packet forensics analyzer.

Reads pcap captures and firewall configurations, then models how the Linux
kernel's netfilter subsystem processes each packet through the inbound chain
pipeline with connection tracking.
"""

import json
import os
import glob
import sys

from scapy.all import rdpcap, IP, TCP, UDP, conf
conf.verb = 0


def extract_packets(pcap_path):
    """Read a pcap file and return packet dicts with 5-tuple fields."""
    raw = rdpcap(pcap_path)
    packets = []
    for pkt in raw:
        if IP not in pkt:
            continue
        rec = {"src_ip": pkt[IP].src, "dst_ip": pkt[IP].dst}
        if TCP in pkt:
            rec["proto"] = "tcp"
            rec["src_port"] = pkt[TCP].sport
            rec["dst_port"] = pkt[TCP].dport
        elif UDP in pkt:
            rec["proto"] = "udp"
            rec["src_port"] = pkt[UDP].sport
            rec["dst_port"] = pkt[UDP].dport
        else:
            continue
        packets.append(rec)
    return packets


def match_rule(packet, rule_match):
    """Check if all fields in rule_match match the packet."""
    for field, value in rule_match.items():
        if packet.get(field) != value:
            return False
    return True


def evaluate_chain(packet, rules):
    """Evaluate packet against chain rules; return first matching action or ACCEPT."""
    for rule in rules:
        if match_rule(packet, rule.get("match", {})):
            return rule["action"]
    return "ACCEPT"


def flow_key(packet):
    """Extract the conntrack flow 5-tuple."""
    return (
        packet["proto"],
        packet["src_ip"],
        packet["src_port"],
        packet["dst_ip"],
        packet["dst_port"],
    )


def simulate(packets, config):
    """Model netfilter processing for a packet sequence with given config."""
    conntrack_max = config["conntrack_max"]
    rules = config["rules"]

    conntrack_table = set()
    counters = {
        "raw_PREROUTING": 0,
        "mangle_PREROUTING": 0,
        "filter_INPUT": 0,
    }
    conntrack_drops = 0
    verdicts = []

    for pkt in packets:
        # Stage 1: raw/PREROUTING
        counters["raw_PREROUTING"] += 1
        raw_action = evaluate_chain(pkt, rules.get("raw_PREROUTING", []))
        notrack = raw_action == "NOTRACK"

        if raw_action == "DROP":
            verdicts.append("DROP")
            continue

        # Stage 2: conntrack decision
        created_new = False
        fk = None

        if not notrack:
            fk = flow_key(pkt)
            if fk in conntrack_table:
                pass  # existing confirmed flow
            else:
                if len(conntrack_table) >= conntrack_max:
                    conntrack_drops += 1
                    verdicts.append("CT_DROP")
                    continue
                else:
                    conntrack_table.add(fk)
                    created_new = True

        # Stage 3: mangle/PREROUTING
        counters["mangle_PREROUTING"] += 1
        mangle_action = evaluate_chain(pkt, rules.get("mangle_PREROUTING", []))

        if mangle_action == "DROP":
            if created_new and fk is not None:
                conntrack_table.discard(fk)
            verdicts.append("DROP")
            continue

        # Stage 4: filter/INPUT
        counters["filter_INPUT"] += 1
        filter_action = evaluate_chain(pkt, rules.get("filter_INPUT", []))

        if filter_action == "DROP":
            if created_new and fk is not None:
                conntrack_table.discard(fk)
            verdicts.append("DROP")
        else:
            verdicts.append("ACCEPT")

    return {
        "counters": counters,
        "conntrack_entries": len(conntrack_table),
        "conntrack_drops": conntrack_drops,
        "verdicts": verdicts,
    }


def main():
    incidents_dir = "/app/incidents"
    results_dir = "/app/results"
    os.makedirs(results_dir, exist_ok=True)

    pcap_files = sorted(glob.glob(os.path.join(incidents_dir, "*.pcap")))
    if not pcap_files:
        print("No pcap files found in", incidents_dir, file=sys.stderr)
        sys.exit(1)

    for pcap_path in pcap_files:
        name = os.path.splitext(os.path.basename(pcap_path))[0]
        config_path = os.path.join(incidents_dir, "{}.json".format(name))

        if not os.path.isfile(config_path):
            print("Config not found: {}".format(config_path), file=sys.stderr)
            sys.exit(1)

        with open(config_path) as f:
            config = json.load(f)

        packets = extract_packets(pcap_path)
        result = simulate(packets, config)

        output_path = os.path.join(results_dir, "{}.json".format(name))
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        print("Processed: {}".format(name))


if __name__ == "__main__":
    main()
