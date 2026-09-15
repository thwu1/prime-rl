#!/usr/bin/env python3
"""
Reference solution for DDoS traffic evaluation task.

Steps:
  1. Implement CIDR and payload-length matching in evaluate.py
  2. Analyze the traffic capture to identify attack patterns
  3. Create a classification of attack traffic
  4. Evaluate all candidate strategies
  5. Design an optimal filtering strategy
  6. Evaluate the optimal strategy
"""

import json
import os
import subprocess
import sys
from collections import Counter


def fix_evaluate():
    """Implement the two TODO items in evaluate.py."""
    with open("/app/evaluate.py") as f:
        code = f.read()

    # Fix 1: CIDR subnet matching
    old_cidr = (
        '    if "src_network" in rule_match:\n'
        '        # TODO: Implement CIDR subnet matching using the '
        'ipaddress module.\n'
        '        # Check whether packet.src_ip falls within the network '
        'specified\n'
        '        # by rule_match["src_network"] (e.g., "198.18.0.0/15").\n'
        '        # Return False if the packet\'s source IP is NOT in the '
        'network.\n'
        '        raise NotImplementedError(\n'
        '            "CIDR subnet matching not yet implemented. "\n'
        '            "Use ipaddress.ip_address() and '
        'ipaddress.ip_network() "\n'
        '            "to check if packet.src_ip is within '
        'rule_match[\'src_network\']."\n'
        '        )'
    )
    new_cidr = (
        '    if "src_network" in rule_match:\n'
        '        net = ip_network(rule_match["src_network"], strict=False)\n'
        '        if ip_address(packet.src_ip) not in net:\n'
        '            return False'
    )
    code = code.replace(old_cidr, new_cidr)

    # Fix 2: Payload length matching
    old_payload = (
        '    if "min_payload_length" in rule_match:\n'
        '        # TODO: Implement payload length comparison.\n'
        '        # Check whether packet.payload_length is strictly '
        'greater than\n'
        '        # the value specified in rule_match["min_payload_length"].\n'
        '        # Return False if the payload is NOT larger than the '
        'threshold.\n'
        '        raise NotImplementedError(\n'
        '            "Payload length matching not yet implemented. "\n'
        '            "Compare packet.payload_length against "\n'
        '            "rule_match[\'min_payload_length\']."\n'
        '        )'
    )
    new_payload = (
        '    if "min_payload_length" in rule_match:\n'
        '        if packet.payload_length <= '
        'rule_match["min_payload_length"]:\n'
        '            return False'
    )
    code = code.replace(old_payload, new_payload)

    with open("/app/evaluate.py", "w") as f:
        f.write(code)
    print("Fixed evaluate.py: CIDR and payload length matching implemented")


def analyze_traffic():
    """Use tshark to analyze traffic patterns in the pcap."""
    pcap = "/app/data/traffic.pcap"

    # Protocol hierarchy
    r = subprocess.run(
        ["tshark", "-r", pcap, "-q", "-z", "io,phs"],
        capture_output=True, text=True)
    print("Protocol hierarchy:")
    print(r.stdout)

    # TCP SYN sources by /16 prefix
    r = subprocess.run(
        ["tshark", "-r", pcap,
         "-Y", "tcp.flags.syn==1 && tcp.flags.ack==0",
         "-T", "fields", "-e", "ip.src", "-e", "tcp.dstport"],
        capture_output=True, text=True)

    syn_by_prefix = Counter()
    for line in r.stdout.strip().split("\n"):
        if line:
            parts = line.split("\t")
            if len(parts) >= 1:
                prefix = ".".join(parts[0].split(".")[:2])
                syn_by_prefix[prefix] += 1

    print("TCP SYN by /16 prefix (top 5):")
    for prefix, count in syn_by_prefix.most_common(5):
        print("  {}.0.0/16: {} SYN packets".format(prefix, count))

    # UDP analysis: source port and payload sizes
    r = subprocess.run(
        ["tshark", "-r", pcap, "-Y", "udp",
         "-T", "fields", "-e", "ip.src", "-e", "udp.srcport",
         "-e", "udp.dstport", "-e", "udp.length"],
        capture_output=True, text=True)

    udp_sport53_large = 0
    udp_sport53_small = 0
    for line in r.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 4:
            src_port = int(parts[1])
            udp_len = int(parts[3])
            if src_port == 53:
                # UDP length includes 8-byte header; payload = length - 8
                payload = udp_len - 8
                if payload > 200:
                    udp_sport53_large += 1
                else:
                    udp_sport53_small += 1

    print("\nUDP with src_port=53:")
    print("  Large payload (>200 bytes): {}".format(udp_sport53_large))
    print("  Small payload (<=200 bytes): {}".format(udp_sport53_small))

    # Identify attack patterns
    flood_prefix = syn_by_prefix.most_common(1)[0][0]
    print("\n--- Attack Identification ---")
    print("SYN flood: {} TCP SYN from {}.0.0/15 to port 80".format(
        syn_by_prefix[flood_prefix], flood_prefix))
    print("DNS amplification: {} large UDP from src_port 53".format(
        udp_sport53_large))
    print("Legitimate DNS responses: {} small UDP from src_port 53".format(
        udp_sport53_small))

    return {"flood_prefix": flood_prefix}


def create_classification(analysis):
    """Create attack classification based on traffic analysis."""
    classification = {
        "attack_patterns": [
            {
                "name": "syn_flood",
                "description": (
                    "TCP SYN flood from {}.0.0/15 targeting port 80".format(
                        analysis["flood_prefix"])),
                "criteria": {
                    "protocol": "tcp",
                    "src_network": "{}.0.0/15".format(
                        analysis["flood_prefix"]),
                    "dst_port": 80
                }
            },
            {
                "name": "dns_amplification",
                "description": (
                    "DNS amplification: large UDP responses (>200 bytes) "
                    "from src_port 53"),
                "criteria": {
                    "protocol": "udp",
                    "src_port": 53,
                    "min_payload_length": 200
                }
            }
        ]
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/classification.json", "w") as f:
        json.dump(classification, f, indent=2)
    print("Wrote /app/output/classification.json")
    return classification


def evaluate_all_strategies():
    """Evaluate all candidate strategies using the framework."""
    strategy_dir = "/app/strategies"
    scores = {}

    for fname in sorted(os.listdir(strategy_dir)):
        if not fname.endswith(".json"):
            continue
        strat_path = os.path.join(strategy_dir, fname)
        result = subprocess.run(
            ["python3", "/app/evaluate.py",
             "--pcap", "/app/data/traffic.pcap",
             "--strategy", strat_path,
             "--classification", "/app/output/classification.json"],
            capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            name = data["strategy_name"]
            scores[name] = data["metrics"]
            print("  {}: F1={:.4f}, FPR={:.4f}".format(
                name, data["metrics"]["f1"], data["metrics"]["fpr"]))
        else:
            print("  Error evaluating {}: {}".format(
                fname, result.stderr), file=sys.stderr)

    with open("/app/output/strategy_scores.json", "w") as f:
        json.dump(scores, f, indent=2)
    print("Wrote /app/output/strategy_scores.json")
    return scores


def create_optimal_strategy():
    """Design the optimal filtering strategy."""
    optimal = {
        "name": "optimal",
        "rules": [
            {
                "match": {"src_network": "198.18.0.0/15"},
                "action": "drop"
            },
            {
                "match": {
                    "protocol": "udp",
                    "src_port": 53,
                    "min_payload_length": 200
                },
                "action": "drop"
            }
        ]
    }

    with open("/app/output/optimal_strategy.json", "w") as f:
        json.dump(optimal, f, indent=2)
    print("Wrote /app/output/optimal_strategy.json")


def evaluate_optimal():
    """Evaluate the optimal strategy."""
    result = subprocess.run(
        ["python3", "/app/evaluate.py",
         "--pcap", "/app/data/traffic.pcap",
         "--strategy", "/app/output/optimal_strategy.json",
         "--classification", "/app/output/classification.json",
         "--output", "/app/output/optimal_score.json"],
        capture_output=True, text=True)
    if result.returncode == 0:
        data = json.loads(result.stdout)
        m = data["metrics"]
        print("  Optimal: F1={:.4f}, FPR={:.4f} "
              "(TP={}, FP={}, FN={}, TN={})".format(
                  m["f1"], m["fpr"], m["tp"], m["fp"], m["fn"], m["tn"]))
    else:
        print("  Error: {}".format(result.stderr), file=sys.stderr)
        sys.exit(1)


def main():
    print("=== Step 1: Fix evaluation framework ===")
    fix_evaluate()

    print("\n=== Step 2: Analyze traffic with tshark ===")
    analysis = analyze_traffic()

    print("\n=== Step 3: Create attack classification ===")
    create_classification(analysis)

    print("\n=== Step 4: Evaluate candidate strategies ===")
    evaluate_all_strategies()

    print("\n=== Step 5: Design optimal strategy ===")
    create_optimal_strategy()

    print("\n=== Step 6: Evaluate optimal strategy ===")
    evaluate_optimal()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
