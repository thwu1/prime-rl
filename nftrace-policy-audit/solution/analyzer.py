#!/usr/bin/env python3
"""
nftables trace forensics analyzer.

Parses raw `nft monitor trace` output, reconstructs per-flow packet paths,
detects NAT transformations, validates against zone-based firewall policy,
and identifies policy violations.
"""

import json
import re
from collections import defaultdict


def parse_trace_file(path):
    """Parse nft monitor trace output into events grouped by trace ID."""
    flows = defaultdict(list)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"trace id ([0-9a-fA-F]+) ip (\S+) (\S+) (.+)", line)
            if not m:
                continue
            trace_id, table, chain, rest = m.groups()
            event = {"table": table, "chain": chain}

            if rest.startswith("packet:"):
                event["type"] = "packet"
                event["fields"] = parse_packet_fields(rest[len("packet:"):].strip())
            elif rest.startswith("rule "):
                event["type"] = "rule"
                event["rule_text"] = rest
                vm = re.search(r"\(verdict (\w+)\)", rest)
                if vm:
                    event["verdict"] = vm.group(1)
                if "masquerade" in rest:
                    event["nat"] = "masquerade"
                dm = re.search(r"dnat to ([\d.]+):(\d+)", rest)
                if dm:
                    event["nat"] = "dnat"
                    event["dnat_addr"] = dm.group(1)
                    event["dnat_port"] = int(dm.group(2))
                sm = re.search(r"snat to ([\d.]+)", rest)
                if sm:
                    event["nat"] = "snat"
                    event["snat_addr"] = sm.group(1)
            elif rest.startswith("verdict "):
                event["type"] = "verdict"
                event["verdict"] = rest.split()[1]
            elif rest.startswith("policy "):
                event["type"] = "policy"
                event["verdict"] = rest.split()[1]
            else:
                event["type"] = "unknown"

            flows[trace_id].append(event)
    return flows


def parse_packet_fields(s):
    """Extract structured fields from a packet description string."""
    fields = {}
    m = re.search(r'iif "([^"]+)"', s)
    if m:
        fields["iif"] = m.group(1)
    m = re.search(r'oif "([^"]+)"', s)
    if m:
        fields["oif"] = m.group(1)
    m = re.search(r"ip saddr (\S+)", s)
    if m:
        fields["ip_saddr"] = m.group(1)
    m = re.search(r"ip daddr (\S+)", s)
    if m:
        fields["ip_daddr"] = m.group(1)
    m = re.search(r"ip ttl (\d+)", s)
    if m:
        fields["ip_ttl"] = int(m.group(1))
    m = re.search(r"ip protocol (\S+)", s)
    if m:
        fields["ip_protocol"] = m.group(1)
    m = re.search(r"tcp sport (\d+)", s)
    if m:
        fields["tcp_sport"] = int(m.group(1))
    m = re.search(r"tcp dport (\d+)", s)
    if m:
        fields["tcp_dport"] = int(m.group(1))
    m = re.search(r"udp sport (\d+)", s)
    if m:
        fields["udp_sport"] = int(m.group(1))
    m = re.search(r"udp dport (\d+)", s)
    if m:
        fields["udp_dport"] = int(m.group(1))
    m = re.search(r"icmp type (\S+)", s)
    if m:
        fields["icmp_type"] = m.group(1)
    m = re.search(r"icmp id (\d+)", s)
    if m:
        fields["icmp_id"] = int(m.group(1))
    return fields


def analyze_flow(trace_id, events, iface_zones, policy):
    """Analyze a single flow from its trace events."""
    # First packet event → original addresses
    first_pkt = None
    for e in events:
        if e["type"] == "packet":
            first_pkt = e["fields"]
            break
    if not first_pkt:
        return None

    protocol = first_pkt.get("ip_protocol", "unknown")
    src_addr = first_pkt.get("ip_saddr")
    dst_addr = first_pkt.get("ip_daddr")

    src_port = None
    dst_port = None
    if protocol == "tcp":
        src_port = first_pkt.get("tcp_sport")
        dst_port = first_pkt.get("tcp_dport")
    elif protocol == "udp":
        src_port = first_pkt.get("udp_sport")
        dst_port = first_pkt.get("udp_dport")

    # Interfaces: iif from first packet, oif from first packet that has it
    ingress = first_pkt.get("iif")
    egress = None
    for e in events:
        if e["type"] == "packet" and "oif" in e.get("fields", {}):
            egress = e["fields"]["oif"]
            break

    # Ordered chain path (deduplicated, preserving order)
    chain_path = []
    seen = set()
    for e in events:
        key = f"{e['table']}/{e['chain']}"
        if key not in seen:
            chain_path.append(key)
            seen.add(key)

    # Final verdict: last verdict-bearing event wins
    verdict = "accept"
    for e in reversed(events):
        if e["type"] in ("verdict", "policy") and "verdict" in e:
            verdict = e["verdict"]
            break
        if e["type"] == "rule" and "verdict" in e:
            verdict = e["verdict"]
            break

    # NAT detection
    nat_type = None
    dnat_port = None
    for e in events:
        if e["type"] == "rule":
            nat_kind = e.get("nat")
            if nat_kind in ("masquerade", "snat"):
                nat_type = "snat"
            elif nat_kind == "dnat":
                nat_type = "dnat"
                dnat_port = e.get("dnat_port")

    # Zones from interfaces
    from_zone = iface_zones.get(ingress, "UNKNOWN")
    to_zone = iface_zones.get(egress, "UNKNOWN") if egress else "UNKNOWN"

    # Policy evaluation — for DNAT flows use post-DNAT destination port
    eval_dst_port = dnat_port if (nat_type == "dnat" and dnat_port is not None) else dst_port
    policy_compliant = evaluate_policy(
        from_zone, to_zone, protocol, eval_dst_port, verdict, policy
    )

    return {
        "trace_id": trace_id,
        "protocol": protocol,
        "src_addr": src_addr,
        "dst_addr": dst_addr,
        "src_port": src_port,
        "dst_port": dst_port,
        "ingress_interface": ingress,
        "egress_interface": egress,
        "from_zone": from_zone,
        "to_zone": to_zone,
        "verdict": verdict,
        "chain_path": chain_path,
        "nat_type": nat_type,
        "policy_compliant": policy_compliant,
    }


def evaluate_policy(from_zone, to_zone, protocol, dst_port, actual_verdict, policy):
    """Return True if actual_verdict matches the expected policy action."""
    global_default = policy.get("default_action", "drop")
    expected = global_default

    for entry in policy.get("inter_zone_policies", []):
        if entry["from_zone"] == from_zone and entry["to_zone"] == to_zone:
            matched_rule = False
            for rule in entry.get("rules", []):
                rule_proto = rule.get("protocol", "any")
                if rule_proto == "any" or rule_proto == protocol:
                    if "dst_ports" in rule:
                        if dst_port is not None and dst_port in rule["dst_ports"]:
                            expected = rule["action"]
                            matched_rule = True
                            break
                    else:
                        expected = rule["action"]
                        matched_rule = True
                        break
            if not matched_rule:
                expected = entry.get("default_action", global_default)
            break

    return actual_verdict == expected


def main():
    with open("/app/topology.json") as f:
        topology = json.load(f)
    with open("/app/policy.json") as f:
        policy = json.load(f)

    # Build interface → zone map
    iface_zones = {}
    for iface, info in topology.get("interfaces", {}).items():
        iface_zones[iface] = info["zone"]

    # Parse trace
    trace_flows = parse_trace_file("/app/capture.trace")

    # Analyze each flow
    flows = []
    for tid, events in trace_flows.items():
        flow = analyze_flow(tid, events, iface_zones, policy)
        if flow:
            flows.append(flow)
    flows.sort(key=lambda f: f["trace_id"])

    # Identify policy violations
    violations = []
    for flow in flows:
        if not flow["policy_compliant"]:
            # Determine expected action for the violation record
            fz, tz = flow["from_zone"], flow["to_zone"]
            expected = policy.get("default_action", "drop")
            for entry in policy.get("inter_zone_policies", []):
                if entry["from_zone"] == fz and entry["to_zone"] == tz:
                    expected = entry.get("default_action", expected)
                    break
            violations.append({
                "trace_id": flow["trace_id"],
                "from_zone": fz,
                "to_zone": tz,
                "expected_action": expected,
                "actual_verdict": flow["verdict"],
            })

    summary = {
        "total_flows": len(flows),
        "accepted_flows": sum(1 for f in flows if f["verdict"] == "accept"),
        "dropped_flows": sum(1 for f in flows if f["verdict"] == "drop"),
        "snat_flows": sum(1 for f in flows if f["nat_type"] == "snat"),
        "dnat_flows": sum(1 for f in flows if f["nat_type"] == "dnat"),
        "policy_violations": len(violations),
    }

    report = {
        "flows": flows,
        "policy_violations": violations,
        "summary": summary,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
