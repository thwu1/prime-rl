#!/usr/bin/env python3
"""
DDoS Filtering Strategy Evaluation Framework

Evaluates packet filtering strategies against network traffic captures.
Applies filtering rules to each packet, compares dispositions against
a classification of attack vs. legitimate traffic, and computes
effectiveness metrics (precision, recall, F1, false positive rate).

Usage:
    python3 evaluate.py --pcap FILE --strategy FILE --classification FILE
    python3 evaluate.py --pcap FILE --strategy FILE --classification FILE --output FILE

Strategy file format (JSON):
{
    "name": "strategy_name",
    "rules": [
        {
            "match": {
                "protocol": "tcp",         # optional: "tcp" or "udp"
                "src_ip": "1.2.3.4",       # optional: exact IP
                "dst_ip": "5.6.7.8",       # optional: exact IP
                "src_network": "10.0.0.0/8",  # optional: CIDR notation
                "src_port": 53,            # optional: exact port
                "dst_port": 80,            # optional: exact port
                "tcp_flags": "S",          # optional: flag string
                "min_payload_length": 200  # optional: payload must be > this
            },
            "action": "drop"
        }
    ]
}

Classification file format (JSON):
{
    "attack_patterns": [
        {
            "name": "pattern_name",
            "criteria": { ... same match syntax as above ... }
        }
    ]
}

Rules and patterns are evaluated in order. First matching rule/pattern wins.
"""

import json
import sys
import argparse
from ipaddress import ip_address, ip_network
from scapy.all import rdpcap, IP, TCP, UDP, conf

conf.verb = 0


class ParsedPacket:
    """Lightweight packet representation for rule matching."""
    __slots__ = ["src_ip", "dst_ip", "protocol", "src_port", "dst_port",
                 "tcp_flags", "payload_length"]

    def __init__(self, src_ip, dst_ip, protocol, src_port, dst_port,
                 tcp_flags=None, payload_length=0):
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.protocol = protocol
        self.src_port = src_port
        self.dst_port = dst_port
        self.tcp_flags = tcp_flags
        self.payload_length = payload_length


def load_packets(pcap_path):
    """Read pcap and return list of ParsedPacket objects."""
    raw_packets = rdpcap(pcap_path)
    packets = []
    for pkt in raw_packets:
        if IP not in pkt:
            continue
        ip_layer = pkt[IP]

        if TCP in pkt:
            tcp = pkt[TCP]
            flags_int = int(tcp.flags)
            flag_str = ""
            if flags_int & 0x02:
                flag_str += "S"
            if flags_int & 0x10:
                flag_str += "A"
            if flags_int & 0x01:
                flag_str += "F"
            if flags_int & 0x04:
                flag_str += "R"
            if flags_int & 0x08:
                flag_str += "P"
            payload_len = len(tcp.payload)
            packets.append(ParsedPacket(
                src_ip=ip_layer.src, dst_ip=ip_layer.dst,
                protocol="tcp",
                src_port=tcp.sport, dst_port=tcp.dport,
                tcp_flags=flag_str, payload_length=payload_len
            ))
        elif UDP in pkt:
            udp = pkt[UDP]
            payload_len = len(udp.payload)
            packets.append(ParsedPacket(
                src_ip=ip_layer.src, dst_ip=ip_layer.dst,
                protocol="udp",
                src_port=udp.sport, dst_port=udp.dport,
                tcp_flags=None, payload_length=payload_len
            ))
    return packets


def match_rule(packet, rule_match):
    """
    Check if a packet matches a rule's match criteria.

    Returns True if packet matches ALL specified criteria.
    """
    # Protocol match
    if "protocol" in rule_match:
        if packet.protocol != rule_match["protocol"]:
            return False

    # Exact IP matches
    if "src_ip" in rule_match:
        if packet.src_ip != rule_match["src_ip"]:
            return False
    if "dst_ip" in rule_match:
        if packet.dst_ip != rule_match["dst_ip"]:
            return False

    # CIDR network match
    if "src_network" in rule_match:
        # TODO: Implement CIDR subnet matching using the ipaddress module.
        # Check whether packet.src_ip falls within the network specified
        # by rule_match["src_network"] (e.g., "198.18.0.0/15").
        # Return False if the packet's source IP is NOT in the network.
        raise NotImplementedError(
            "CIDR subnet matching not yet implemented. "
            "Use ipaddress.ip_address() and ipaddress.ip_network() "
            "to check if packet.src_ip is within rule_match['src_network']."
        )

    # Port matches
    if "src_port" in rule_match:
        if packet.src_port != rule_match["src_port"]:
            return False
    if "dst_port" in rule_match:
        if packet.dst_port != rule_match["dst_port"]:
            return False

    # TCP flags match
    if "tcp_flags" in rule_match:
        if packet.tcp_flags != rule_match["tcp_flags"]:
            return False

    # Payload length match
    if "min_payload_length" in rule_match:
        # TODO: Implement payload length comparison.
        # Check whether packet.payload_length is strictly greater than
        # the value specified in rule_match["min_payload_length"].
        # Return False if the payload is NOT larger than the threshold.
        raise NotImplementedError(
            "Payload length matching not yet implemented. "
            "Compare packet.payload_length against "
            "rule_match['min_payload_length']."
        )

    return True


def apply_strategy(packets, strategy):
    """Apply a filtering strategy to packets. Returns per-packet dispositions."""
    rules = strategy.get("rules", [])
    dispositions = []

    for packet in packets:
        dropped = False
        for rule in rules:
            try:
                if match_rule(packet, rule.get("match", {})):
                    if rule.get("action") == "drop":
                        dropped = True
                        break
            except NotImplementedError as e:
                print("Warning: {}".format(e), file=sys.stderr)
                continue
        dispositions.append("drop" if dropped else "accept")

    return dispositions


def classify_packets(packets, classification):
    """Classify packets as attack or legitimate based on attack patterns."""
    patterns = classification.get("attack_patterns", [])
    labels = []

    for packet in packets:
        is_attack = False
        for pattern in patterns:
            criteria = pattern.get("criteria", {})
            try:
                if match_rule(packet, criteria):
                    is_attack = True
                    break
            except NotImplementedError as e:
                print("Warning: {}".format(e), file=sys.stderr)
                continue
        labels.append("attack" if is_attack else "legitimate")

    return labels


def compute_metrics(dispositions, labels):
    """Compute precision, recall, F1, and false positive rate."""
    tp = fp = tn = fn = 0

    for disp, label in zip(dispositions, labels):
        if disp == "drop" and label == "attack":
            tp += 1
        elif disp == "drop" and label == "legitimate":
            fp += 1
        elif disp == "accept" and label == "attack":
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) > 0 else 0.0)
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "fpr": round(fpr, 6)
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate DDoS filtering strategy effectiveness")
    parser.add_argument("--pcap", required=True, help="Path to pcap file")
    parser.add_argument("--strategy", required=True,
                        help="Path to strategy JSON file")
    parser.add_argument("--classification", required=True,
                        help="Path to classification JSON file")
    parser.add_argument("--output",
                        help="Path to write results JSON (optional)")
    args = parser.parse_args()

    print("Loading packets from {}...".format(args.pcap), file=sys.stderr)
    packets = load_packets(args.pcap)
    print("Loaded {} packets".format(len(packets)), file=sys.stderr)

    with open(args.strategy) as f:
        strategy = json.load(f)
    with open(args.classification) as f:
        classification = json.load(f)

    dispositions = apply_strategy(packets, strategy)
    labels = classify_packets(packets, classification)
    metrics = compute_metrics(dispositions, labels)

    result = {
        "strategy_name": strategy.get("name", "unknown"),
        "total_packets": len(packets),
        "metrics": metrics
    }

    output = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
