#!/usr/bin/env python3
"""
Reference solver for HTB Traffic Shaping Forensics.

Parses raw tc class/filter output, cross-references with flow records
and the intended hierarchy spec, identifies three misconfigurations,
and produces diagnosis.json + fix.sh.

"""
import re
import json
import csv
import os
import glob
import stat


def parse_tc_dump(filepath):
    """Parse a raw tc -s class show dump into a dict of class data."""
    with open(filepath) as f:
        text = f.read()

    classes = {}
    blocks = re.split(r'\n(?=class htb)', text.strip())

    for block in blocks:
        if not block.strip():
            continue

        header = block.split('\n')[0]
        cid_m = re.search(r'class htb (\S+)', header)
        if not cid_m:
            continue
        cid = cid_m.group(1)

        rate_m = re.search(r'rate (\S+)', header)
        ceil_m = re.search(r'ceil (\S+)', header)
        quantum_m = re.search(r'quantum (\d+)', header)
        parent_m = re.search(r'parent (\S+)', header)

        sent_m = re.search(
            r'Sent (\d+) bytes (\d+) pkt '
            r'\(dropped (\d+), overlimits (\d+)', block)
        backlog_m = re.search(r'backlog (\d+)b (\d+)p', block)
        lended_m = re.search(r'lended: (\d+) borrowed: (\d+)', block)

        classes[cid] = {
            'rate': rate_m.group(1) if rate_m else None,
            'ceil': ceil_m.group(1) if ceil_m else None,
            'quantum': int(quantum_m.group(1)) if quantum_m else None,
            'parent': parent_m.group(1) if parent_m else None,
            'is_root': 'root' in header,
            'is_leaf': 'leaf' in header,
            'sent_bytes': int(sent_m.group(1)) if sent_m else 0,
            'sent_pkts': int(sent_m.group(2)) if sent_m else 0,
            'dropped': int(sent_m.group(3)) if sent_m else 0,
            'overlimits': int(sent_m.group(4)) if sent_m else 0,
            'backlog_bytes': int(backlog_m.group(1)) if backlog_m else 0,
            'lended': int(lended_m.group(1)) if lended_m else 0,
            'borrowed': int(lended_m.group(2)) if lended_m else 0,
        }

    return classes


def parse_rate(rate_str):
    """Convert rate string like '100Mbit' to bits per second."""
    if not rate_str:
        return 0
    if rate_str.endswith('Mbit'):
        return int(rate_str[:-4]) * 1_000_000
    if rate_str.endswith('Kbit'):
        return int(rate_str[:-4]) * 1_000
    if rate_str.endswith('bit'):
        return int(rate_str[:-3])
    return int(rate_str)


def parse_filters(filepath):
    """Parse tc -s filter show output, extract rules sorted by pref."""
    with open(filepath) as f:
        lines = f.readlines()

    filters = []
    for i, line in enumerate(lines):
        if 'flowid' not in line:
            continue

        flowid_m = re.search(r'flowid (\S+)', line)
        pref_m = re.search(r'pref (\d+)', line)
        if not flowid_m:
            continue

        if i + 1 < len(lines) and 'match' in lines[i + 1]:
            match_line = lines[i + 1].strip()
            m = re.match(r'match (\S+)/(\S+) at (\d+)', match_line)
            if not m:
                continue

            hits = 0
            success = 0
            if i + 2 < len(lines):
                hit_m = re.search(
                    r'rule hit (\d+) success (\d+)', lines[i + 2])
                if hit_m:
                    hits = int(hit_m.group(1))
                    success = int(hit_m.group(2))

            filters.append({
                'flowid': flowid_m.group(1),
                'pref': int(pref_m.group(1)) if pref_m else 999,
                'match_val': m.group(1),
                'match_mask': m.group(2),
                'offset': int(m.group(3)),
                'hits': hits,
                'success': success,
            })

    filters.sort(key=lambda f: (f['pref'], f.get('order', 0)))
    return filters


def classify_flow(flow, filters):
    """Simulate u32 filter classification for a flow."""
    dscp = int(flow['dscp'])
    tos = dscp << 2
    dst_port = int(flow['dst_port'])
    src_port = int(flow['src_port'])

    for filt in filters:
        offset = filt['offset']
        match_val = int(filt['match_val'], 16)
        match_mask = int(filt['match_mask'], 16)

        if offset == 0:
            # IP header bytes 0-3: [version+IHL][ToS][TotalLen]
            word = (0x45 << 24) | (tos << 16)
            if (word & match_mask) == match_val:
                return filt['flowid']
        elif offset == 20:
            # Transport header: [src_port][dst_port]
            word = (src_port << 16) | dst_port
            if (word & match_mask) == match_val:
                return filt['flowid']

    return "1:300"  # default class


def main():
    # Load last tc dump for current configuration state
    dump_files = sorted(glob.glob("/app/captures/tc_dump_*.txt"))
    last_dump = parse_tc_dump(dump_files[-1])

    # Load intended hierarchy
    with open("/app/hierarchy.json") as f:
        hierarchy = json.load(f)

    # Load filter rules
    filters = parse_filters("/app/filters.txt")

    # Load flow records
    flows = []
    with open("/app/flows.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            flows.append(row)

    issues = []

    # --- Issue 1: Filter misclassification ---
    misclassified = []
    for flow in flows:
        actual_class = classify_flow(flow, filters)
        if actual_class != flow['expected_class']:
            misclassified.append({
                'flow_id': flow['flow_id'],
                'expected': flow['expected_class'],
                'actual': actual_class,
                'dscp': flow['dscp'],
            })

    if misclassified:
        affected = set(m['expected'] for m in misclassified)
        voip_filter = [f for f in filters if f['flowid'] == '1:100']
        detail_parts = []
        if voip_filter:
            vf = voip_filter[0]
            match_byte = int(vf['match_val'][2:4], 16)
            actual_dscp = match_byte >> 2
            detail_parts.append(
                f"u32 filter for flowid 1:100 matches ToS byte "
                f"0x{match_byte:02X} (DSCP {actual_dscp}) but VoIP traffic "
                f"uses DSCP EF (46, ToS 0xB8). "
                f"Filter hit count is {vf['hits']}, confirming no traffic "
                f"matches this rule."
            )
        detail_parts.append(
            f"{len(misclassified)} flows with DSCP 46 fall through to "
            f"default class 1:300 instead of reaching 1:100."
        )

        issues.append({
            "affected_class": "1:100",
            "root_cause": " ".join(detail_parts),
            "misclassified_flow_ids": [m['flow_id'] for m in misclassified],
            "evidence": {
                "filter_match_value": voip_filter[0]['match_val']
                if voip_filter else None,
                "filter_hits": voip_filter[0]['hits']
                if voip_filter else None,
                "affected_flows": len(misclassified),
            },
        })

    # --- Issue 2: Ceil vs hierarchy spec ---
    for cid in last_dump:
        if cid not in hierarchy:
            continue
        actual_ceil = parse_rate(last_dump[cid]['ceil'])
        intended_ceil = hierarchy[cid].get('ceil_bps', 0)
        if actual_ceil and intended_ceil and actual_ceil != intended_ceil:
            actual_rate = parse_rate(last_dump[cid]['rate'])
            issues.append({
                "affected_class": cid,
                "root_cause": (
                    f"Class {cid} has ceil {last_dump[cid]['ceil']} which "
                    f"equals its rate ({last_dump[cid]['rate']}), but the "
                    f"design spec sets ceil to "
                    f"{intended_ceil // 1_000_000}Mbit. "
                    f"With ceil == rate the class cannot borrow surplus "
                    f"bandwidth from its parent, capping throughput at "
                    f"{last_dump[cid]['rate']} regardless of available "
                    f"capacity."
                ),
                "evidence": {
                    "actual_ceil": last_dump[cid]['ceil'],
                    "intended_ceil_bps": intended_ceil,
                    "actual_rate": last_dump[cid]['rate'],
                },
            })

    # --- Issue 3: Quantum disparity among siblings ---
    children_map = {}
    for cid, data in last_dump.items():
        parent = data.get('parent')
        if parent:
            children_map.setdefault(parent, []).append(cid)

    for parent_cid, children in children_map.items():
        leaf_children = [c for c in children if last_dump[c].get('is_leaf')]
        if len(leaf_children) < 2:
            continue

        quantums = {}
        for c in leaf_children:
            q = last_dump[c].get('quantum')
            if q is not None:
                quantums[c] = q

        if len(quantums) < 2:
            continue

        qvals = list(quantums.values())
        if max(qvals) > 10 * min(qvals):
            max_q_class = max(quantums, key=quantums.get)
            min_q_class = min(quantums, key=quantums.get)
            ratio = quantums[max_q_class] // quantums[min_q_class]
            issues.append({
                "affected_class": max_q_class,
                "root_cause": (
                    f"Class {max_q_class} has quantum {quantums[max_q_class]} "
                    f"while sibling {min_q_class} has quantum "
                    f"{quantums[min_q_class]}. This {ratio}:1 ratio causes "
                    f"severe scheduling unfairness in HTB's deficit "
                    f"round-robin mechanism, allowing {max_q_class} to "
                    f"dequeue {ratio}x more data per scheduling round than "
                    f"its sibling."
                ),
                "evidence": {
                    "quantum_values": quantums,
                    "ratio": ratio,
                },
            })

    # Write diagnosis.json
    with open("/app/diagnosis.json", "w") as f:
        json.dump({"issues": issues}, f, indent=2)

    # Write fix.sh
    fix_lines = [
        "#!/bin/bash",
        "# HTB QoS remediation — in-place fixes",
        "",
        "# Fix VoIP filter: correct DSCP match from 44 (0xB0) to 46/EF "
        "(0xB8)",
        "tc filter del dev eth0 parent 1:0 pref 10",
        "tc filter add dev eth0 protocol ip parent 1:0 pref 10 u32 \\",
        "  match u32 0x00b80000 0x00fc0000 at 0 flowid 1:100",
        "",
        "# Fix Web class ceil: raise from 15Mbit to design-spec 40Mbit",
        "tc class change dev eth0 parent 1:20 classid 1:201 htb \\",
        "  rate 15Mbit ceil 40Mbit burst 1875b cburst 5000b",
        "",
        "# Fix Scavenger quantum: reduce from 60000 to standard 1500",
        "tc class change dev eth0 parent 1:30 classid 1:301 htb \\",
        "  rate 10Mbit ceil 20Mbit burst 1250b cburst 2500b quantum 1500",
        "",
    ]

    with open("/app/fix.sh", "w") as f:
        f.write("\n".join(fix_lines))

    os.chmod("/app/fix.sh", 0o755)
    print("Written /app/diagnosis.json and /app/fix.sh")


if __name__ == "__main__":
    main()
