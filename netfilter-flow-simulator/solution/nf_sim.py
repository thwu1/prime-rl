#!/usr/bin/env python3
"""
Linux netfilter packet flow simulator.

Simulates inbound packet processing through the simplified netfilter pipeline:
  raw/PREROUTING -> conntrack decision -> mangle/PREROUTING -> filter/INPUT

Models conntrack table overflow, NOTRACK bypass, and the interaction between
packet drops and conntrack flow confirmation.
"""

import json
import os
import glob
import sys


def match_rule(packet, rule_match):
    """Check if a packet matches a rule's match criteria.

    All specified fields in rule_match must match the packet's fields.
    An empty match dict matches every packet.
    """
    for field, value in rule_match.items():
        pkt_val = packet.get(field)
        if pkt_val != value:
            return False
    return True


def evaluate_chain(packet, rules):
    """Evaluate packet against a chain's rules. Return action of first matching rule.

    If no rule matches, the default policy (ACCEPT) applies.
    """
    for rule in rules:
        if match_rule(packet, rule.get("match", {})):
            return rule["action"]
    return "ACCEPT"


def flow_key(packet):
    """Extract the conntrack flow 5-tuple from a packet."""
    return (
        packet["proto"],
        packet["src_ip"],
        packet["src_port"],
        packet["dst_ip"],
        packet["dst_port"],
    )


def simulate(scenario):
    """Run the netfilter simulation for a single scenario.

    Returns a dict with counters, conntrack_entries, conntrack_drops, and verdicts.
    """
    conntrack_max = scenario["conntrack_max"]
    rules = scenario["rules"]
    packets = scenario["packets"]

    # Conntrack table: set of confirmed flow keys
    conntrack_table = set()

    # Per-chain packet counters
    counters = {
        "raw_PREROUTING": 0,
        "mangle_PREROUTING": 0,
        "filter_INPUT": 0,
    }

    conntrack_drops = 0
    verdicts = []

    for pkt in packets:
        # ---- Stage 1: raw/PREROUTING ----
        counters["raw_PREROUTING"] += 1
        raw_action = evaluate_chain(pkt, rules.get("raw_PREROUTING", []))

        # Check if packet is marked NOTRACK
        notrack = raw_action == "NOTRACK"

        # If raw action is DROP, packet stops here
        if raw_action == "DROP":
            verdicts.append("DROP")
            continue

        # ---- Stage 2: Conntrack decision ----
        created_new_entry = False
        fk = None

        if not notrack:
            fk = flow_key(pkt)

            if fk in conntrack_table:
                # Existing confirmed flow - packet proceeds
                pass
            else:
                # New flow - check table capacity
                if len(conntrack_table) >= conntrack_max:
                    # Table full - silently drop the packet
                    conntrack_drops += 1
                    verdicts.append("CT_DROP")
                    continue
                else:
                    # Allocate new entry (unconfirmed)
                    conntrack_table.add(fk)
                    created_new_entry = True

        # ---- Stage 3: mangle/PREROUTING ----
        counters["mangle_PREROUTING"] += 1
        mangle_action = evaluate_chain(pkt, rules.get("mangle_PREROUTING", []))

        if mangle_action == "DROP":
            # Remove unconfirmed entry if we just created one
            if created_new_entry and fk is not None:
                conntrack_table.discard(fk)
            verdicts.append("DROP")
            continue

        # ---- Stage 4: filter/INPUT ----
        counters["filter_INPUT"] += 1
        filter_action = evaluate_chain(pkt, rules.get("filter_INPUT", []))

        if filter_action == "DROP":
            # Packet dropped - unconfirmed conntrack entry is removed
            if created_new_entry and fk is not None:
                conntrack_table.discard(fk)
            verdicts.append("DROP")
        else:
            # Packet accepted - conntrack entry is now confirmed
            verdicts.append("ACCEPT")

    return {
        "counters": counters,
        "conntrack_entries": len(conntrack_table),
        "conntrack_drops": conntrack_drops,
        "verdicts": verdicts,
    }


def main():
    scenario_dir = "/app/scenarios"
    output_dir = "/app/results"
    os.makedirs(output_dir, exist_ok=True)

    scenario_files = sorted(glob.glob(os.path.join(scenario_dir, "*.json")))

    if not scenario_files:
        print("No scenario files found in", scenario_dir, file=sys.stderr)
        sys.exit(1)

    for scenario_file in scenario_files:
        with open(scenario_file) as f:
            scenario = json.load(f)

        result = simulate(scenario)

        basename = os.path.basename(scenario_file)
        output_file = os.path.join(output_dir, basename)
        with open(output_file, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Processed: {basename}")


if __name__ == "__main__":
    main()
